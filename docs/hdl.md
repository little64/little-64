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
- `hdl/little64/litex.py` — LiteX-facing profile, wrapper shim, and generic CPU export top
- `hdl/little64/litex_cpu.py` — real LiteX CPU plugin and raw Little64 data-bus alignment bridge
- `hdl/little64/litex_linux_boot.py` — Linux ELF flattening and SPI-flash image packing helpers for the LiteX path
- `hdl/little64/litex_soc.py` — minimal LiteX simulation SoC wrapper and Linux DTS generator
- `hdl/tests/` — Python simulation and unit tests for unit and ISA coverage
- `hdl/tools/build_litex_flash_image.py` — build a bootable SPI-flash image containing stage-0, Linux, and a DTB
- `hdl/tools/export_litex_cpu_verilog.py` — export the generic LiteX CPU wrapper to Verilog
- `hdl/tools/generate_litex_llvm_wrappers.py` — emit LiteX-compatible triple-prefixed LLVM tool wrappers for the repo toolchain
- `hdl/tools/generate_litex_linux_dts.py` — emit a Linux DTS for the LiteX simulation SoC shape
- `hdl/tools/run_verilator_linux_boot_smoke.py` — compiled Linux boot smoke entrypoint using a Verilator-built harness

The current Python/Amaranth simulation path is appropriate for unit and ISA coverage but is too slow for practical full-Linux boot validation. Linux-on-HDL boot validation now uses a compiled Verilator harness instead of the pure Python simulator.

## Linux Boot Smoke

The Linux boot smoke is the practical full-system validation path for the HDL core.
It uses:

- `target/linux_port/build-little64_litex_sim_defconfig/vmlinux` as the LiteX simulation kernel image,
- `hdl/tools/generate_litex_linux_dts.py` to emit a LiteX-simulation DTS under `builddir/hdl-verilator-linux-boot/`,
- `hdl/tools/export_linux_boot_verilog.py` to emit the standalone top-level Verilog,
- `hdl/tools/verilator_linux_boot_smoke_main.cpp` as the compiled harness,
- `hdl/tools/run_verilator_linux_boot_smoke.py` as the normal entrypoint.

## Native LiteX Simulation Flow

The repo now also has a LiteX-native Linux smoke wrapper that uses LiteX's own
simulation toolchain instead of the repo-local custom Verilator harness.

Run it with:

```bash
LITTLE64_LINUX_DEFCONFIG=little64_litex_sim_defconfig target/linux_port/build.sh vmlinux -j1
./.venv/bin/python hdl/tools/run_litex_linux_boot_smoke.py
```

This wrapper:

1. regenerates the LiteX simulation DTS and DTB,
2. rebuilds the SPI-flash image containing stage-0, the kernel, and the DTB,
3. instantiates the existing `Little64LiteXSimSoC` with that flash image,
4. asks LiteX's native simulation builder to generate and compile the simulator,
5. runs the resulting `Vsim` binary and watches the serial stream for the required boot markers.

Use this path when you want to validate the Little64 LiteX integration through
LiteX's own simulator plumbing rather than the standalone custom harness.

Useful options:

| Option | Meaning |
|---|---|
| `--build-only` | Build the LiteX simulator and flash artifacts without running them |
| `--run-only` | Reuse an existing LiteX simulator build from the output directory |
| `--timeout-seconds N` | Stop waiting after `N` wall-clock seconds if the boot markers never appear |
| `--require TEXT` | Override or extend the required serial markers |
| `--jobs N` | Limit LiteX's Verilator compile parallelism |
| `--threads N` | Set LiteX Verilator simulation thread count |

The default output directory for this path is `builddir/hdl-litex-linux-boot/`.

### Prerequisites

Before running the smoke:

```bash
LITTLE64_LINUX_DEFCONFIG=little64_litex_sim_defconfig target/linux_port/build.sh vmlinux -j1
./.venv/bin/pip install -r requirements-hdl.txt
```

The smoke expects the LiteX simulation kernel profile rather than the emulator-oriented default profile.

The HDL requirements file now also carries the LiteX Python packages used by the
simulation-SoC integration layer:

- `litex`
- `litedram`
- `litespi`
- `pythondata-misc-tapcfg`

The wrapper also requires `verilator`, `dtc`, and host development headers for
`json-c` and `libevent` to be installed on the host.

Typical package names are:

- openSUSE / Fedora: `json-c-devel` and `libevent-devel`
- Debian / Ubuntu: `libjson-c-dev` and `libevent-dev`

If `vmlinux`, `verilator`, `dtc`, or the required host headers are missing, the
wrapper exits early with an explicit prerequisite error.

### Recommended Wrapper Flow

Run the smoke through the Python wrapper:

```bash
./.venv/bin/python hdl/tools/run_verilator_linux_boot_smoke.py
```

The wrapper:

1. regenerates `builddir/hdl-verilator-linux-boot/little64-litex-sim.dts` from the LiteX simulation SoC description when the HDL sources change,
2. rebuilds `builddir/hdl-verilator-linux-boot/little64-litex-sim.dtb` from that DTS when needed,
3. regenerates `builddir/hdl-verilator-linux-boot/little64_linux_boot_top.v` when HDL sources change,
4. rebuilds the Verilator binary when the exported Verilog or harness changes,
5. runs the compiled binary against the LiteX simulation `vmlinux` image.

The current default is single-threaded simulation because this harness currently runs faster that way than with wider Verilator threading on the common Linux debug workload.

### Useful Environment Overrides

The wrapper is configured through environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `LITTLE64_VERILATOR_MAX_CYCLES` | `200000000` | Maximum simulated cycles before timing out |
| `LITTLE64_VERILATOR_THREADS` | `1` | Verilator simulation thread count |
| `LITTLE64_VERILATOR_BUILD_JOBS` | host CPU count | Parallelism for compiling the generated C++ model |
| `LITTLE64_VERILATOR_COMPILE_DEBUG` | `1` | Compile the harness with debug-only trace/symbol/page-walk diagnostics enabled (`0` builds a leaner non-debug binary) |
| `LITTLE64_VERILATOR_TIME_SCALE_NS` | `10` | Guest nanoseconds advanced per simulated core cycle in the harness timer model |
| `LITTLE64_VERILATOR_CFLAGS` | `-O3 -std=c++20 -march=native -flto -DNDEBUG` | Extra C++ compile flags for the harness build |
| `LITTLE64_VERILATOR_LDFLAGS` | `-O3 -march=native -flto` | Link flags for the harness build |
| `LITTLE64_VERILATOR_DEBUG_TRACE` | unset | Enables the harness' recent execute-trace capture in failure diagnostics |
| `LITTLE64_VERILATOR_BOOTARGS` | `console=liteuart earlycon=liteuart,0xf0001000 ignore_loglevel loglevel=8` | Bootargs injected into the generated LiteX simulation DTS |

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

# Build and run the lean non-debug harness variant
LITTLE64_VERILATOR_COMPILE_DEBUG=0 \
	./.venv/bin/python hdl/tools/run_verilator_linux_boot_smoke.py

# Override the guest-time scale if timer cadence experiments are needed
LITTLE64_VERILATOR_TIME_SCALE_NS=100 \
	./.venv/bin/python hdl/tools/run_verilator_linux_boot_smoke.py
```

The default `LITTLE64_VERILATOR_TIME_SCALE_NS=10` models a 100 MHz-equivalent
core cadence relative to the Linux-visible 1 GHz nanosecond timer. Larger
values make guest time advance faster per simulated cycle and therefore increase
the effective timer interrupt rate seen by the guest.

The default build keeps the richer diagnostics compiled in. Setting
`LITTLE64_VERILATOR_COMPILE_DEBUG=0` produces a separate `_ndbg` binary that
excludes the symbol-capture, recent-trace, percpu-entry, and page-walk debug
machinery at compile time.

### Success And Failure Contract

The wrapper treats the smoke as successful only after the UART output contains all of these markers:

- `little64-timer: clocksource + clockevent @ 1 GHz`
- `physmap platform flash device:`
- `VFS: Unable to mount root fs`

The root-mount failure is intentional here. This smoke is validating that the HDL core gets far enough into Linux boot to enumerate the LiteX simulation timer and memory-mapped flash path and then reaches the expected no-rootfs panic path.

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

For the current single-threaded harness on the LiteX simulation `vmlinux` image, `1000000` cycles is enough to see only early breadcrumb UART output such as `0`, `B`, and `P`. It is useful for rough performance estimates, not for reaching the later smoke markers.

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
	--kernel target/linux_port/build-little64_litex_sim_defconfig/vmlinux \
	--flash builddir/hdl-verilator-linux-boot/little64-linux-spiflash.bin \
	--max-cycles 1000000 \
	--require 'little64-timer: clocksource + clockevent @ 1 GHz' \
	--require 'physmap platform flash device:' \
	--require 'VFS: Unable to mount root fs'
```

Direct mode avoids the Python wrapper overhead and makes it easier to benchmark different cycle caps or thread-count builds. The current binary accepts only:

- `--kernel <path>`
- `--flash <path>`
- `--max-cycles <n>`
- repeated `--require <substring>`

## LiteX Integration Status

The repo now has a real repo-local LiteX CPU plugin path for Little64 rather
than only a generic exported wrapper. The current LiteX support includes:

- a `little64` LiteX CPU plugin that registers dynamically with LiteX,
- automatic generation of LiteX-compatible `little64-unknown-elf-*` LLVM wrappers backed by the repo's `compilers/bin` tools,
- a bridge that converts the core's raw byte-addressed data-bus behavior into
	standard LiteX word-addressed Wishbone transactions, including split accesses
	across 64-bit boundaries,
- a minimal simulation-first LiteX SoC wrapper for SRAM, integrated RAM or
	LiteDRAM-backed main RAM, LiteUART, a Linux-compatible timer block, a low-MMIO
	breadcrumb UART sink, and memory-mapped SPI flash,
- a SPI-flash boot-image flow that compiles a flash-resident stage-0 loader,
	flattens the Linux PT_LOAD image the same way as the emulator's direct loader,
	places the DTB after the kernel image with the same scratch gap, and jumps with
	the existing Little64 physical-entry contract,
- a Linux DTS generator that emits Little64 CPU and interrupt-controller nodes
	plus LiteUART, the Little64 timer node, the Linux-visible RAM window, and the
	memory-mapped flash node.

Generate a baseline DTS with:

```bash
./.venv/bin/python hdl/tools/generate_litex_linux_dts.py \
	--output builddir/little64-litex.dts \
	--with-spi-flash \
	--integrated-main-ram-size 0x4000000
```

Build a bootable flash image with:

```bash
./.venv/bin/python hdl/tools/build_litex_flash_image.py \
	--kernel-elf target/linux_port/build-little64_litex_sim_defconfig/vmlinux \
	--dtb builddir/hdl-verilator-linux-boot/little64-litex-sim.dtb \
	--output builddir/little64-linux-spiflash.bin
```

### LiteX Stage-0 Entry

The LiteX SPI-flash flow now uses a dedicated stage-0 SoC boot entry at
`target/c_boot/litex_spi_boot.c`.

Its reset sequence is intentionally minimal:

1. enter from the CPU reset PC in SPI flash,
2. establish a temporary low-RAM scratch stack below `0x00100000`,
3. clear stage-0 `.bss`,
4. validate the flash boot header at `0x20000000 + 0x2000`,
5. copy the flattened kernel payload to physical RAM at `KERNEL_PHYS_BASE`,
6. copy the DTB to the post-image scratch-safe address,
7. jump to the kernel physical entry with the existing direct-boot register contract.

The stage-0 loader now emits readable serial status lines while it runs. The
intent is to make simulator and future FPGA bring-up failures diagnosable from a
plain UART capture rather than from terse breadcrumb bytes alone. In the normal
success path it reports entry from SPI flash, `.bss` clearing, flash-header
validation, the kernel and DTB copy plan with addresses and sizes, copy
completion, and the final kernel handoff. Validation failures also print a
descriptive error line before the CPU stops.

The handoff contract remains aligned with the emulator's direct Linux boot path:

- `R1` = physical DTB address,
- `R13` = kernel boot stack top,
- `PC` = kernel physical entry point,
- paging disabled, supervisor mode.

The temporary stage-0 stack lives in low RAM so it does not overlap the kernel
load window starting at `0x00100000`.

Emit the LiteX LLVM wrapper tools with:

```bash
./.venv/bin/python hdl/tools/generate_litex_llvm_wrappers.py \
	--output-dir builddir/litex-toolchain
```

The current LiteX/Linux-facing memory contract intentionally keeps the full RAM
fabric at physical `0x0` for bus-alignment reasons while exporting the Linux DT
memory window from `0x00100000` upward. For the current 64 MiB smoke/harness
configuration, that means Linux sees `0x03f00000` bytes starting at
`0x00100000`, which keeps the first 1 MiB reserved for stage-0 scratch and
other low-memory bootstrap use while still matching the Little64 Linux port's
`KERNEL_PHYS_BASE = 0x00100000` contract.

The simulation SoC also currently leaves the LiteX SoC controller block disabled.
Under this Python 3.13 environment, LiteX's default controller path is hitting a
CSR auto-naming failure during SoC construction. That issue is specific to the
upstream LiteX controller helper rather than the Little64 CPU plugin or bus
bridge, so the current integration keeps UART, memory, and flash bring-up moving
while leaving the controller block for a follow-up compatibility fix.

The Linux tree now also carries a separate LiteX simulation machine profile at
`target/linux_port/linux/arch/little64/boot/dts/little64-litex-sim.dts` with a
matching `little64_litex_sim_defconfig`. This profile uses LiteUART, the
Little64 timer, and the memory-mapped flash node, while the older
`little64.dts` profile remains the emulator-oriented virtual machine contract.

That split is intentional. It gives the LiteX and future FPGA bring-up path a
kernel profile that does not inherit the emulator-only ns16550a UART and PV
block root-disk assumptions.

This is all not final. There will likely be changes to this in the future.

### Meson Integration

The HDL smoke is also wired into the optional HDL Meson subtree as `hdl-linux-boot-smoke`:

```bash
meson test -C builddir-hdl hdl-linux-boot-smoke --print-errorlogs
```

That test simply invokes `hdl/tools/run_verilator_linux_boot_smoke.py`, so the same prerequisites and environment variables apply.

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

The shared `gp` and `ldi` case files under `tests/shared/` are generator-backed.
Refresh them, or fail fast on stale generated content, with:

```bash
./.venv/bin/python tests/shared/generate_instruction_cases.py
./.venv/bin/python tests/shared/generate_instruction_cases.py --check
```

Or enable the optional Meson subtree and run the HDL suite through Meson.

Useful targeted Meson suites after configuring `-Dhdl=enabled`:

```bash
meson test -C builddir-hdl --suite gp --suite ldi --print-errorlogs
meson test -C builddir-hdl --suite jumps --suite memory --print-errorlogs
```

The shared `gp`, `ldi`, `jumps`, and `memory` suites are intended to run both the emulator and HDL backends against the same backend-neutral case files wherever the instruction subset overlaps.
