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

The stable V2 HDL core now performs exception and maskable IRQ vector delivery through the architectural interrupt table and saves `interrupt_epc`, `interrupt_eflags`, and `interrupt_cpu_control` for `IRET`. Interrupt-table fetches run through paging in supervisor mode when paging is enabled, and handler-fetch failure during entry causes architectural lockup. The experimental V3 core now supports precise synchronous exception entry for execute-stage traps, maskable IRQ delivery from `irq_lines`, architectural `IRET` return sequencing, memory-result PC redirects through `R15`, fetch-side MMU/TLB translation for instruction and handler fetch, data-side address translation for paged loads/stores, paged interrupt-vector table lookup, data page-fault handler entry, and `LLR`/`SCR` atomics.

## Source Of Truth

- ISA contract: `docs/hardware/`
- Golden behavioral reference: `host/emulator/cpu.*`, `host/emulator/address_translator.*`
- HDL implementation: `hdl/little64_cores/`
- HDL tests: `hdl/tests/`

If the HDL conflicts with the ISA docs or proving tests, the HDL should be corrected unless the docs are stale.

The current multi-cycle core now lives under `hdl/little64_cores/basic/`.
The new pipelined implementation path lives under `hdl/little64_cores/v2/`.
The experimental next-generation pipeline bring-up now also lives under `hdl/little64_cores/v4/`.
The top-level `hdl/little64_cores/core.py` module remains as a compatibility export for the current default core variant, which is now V4.

## Current Layout

- `hdl/little64_cores/config.py` — core configuration, core-variant selection, and architectural build-time choices
- `hdl/little64_cores/decode.py` — shared decode field metadata definitions only (no executable decode logic)
- `hdl/little64_cores/alu.py` — shared ALU/flags metadata definitions only (no executable ALU logic)
- `hdl/little64_cores/mmu.py` — shared MMU bit and subtype definitions only (no executable translation logic)
- `hdl/little64_cores/wishbone.py` — 64-bit LiteX-compatible bus signal bundle
- `hdl/little64_cores/tlb.py` — shared TLB interface definitions only (no executable TLB logic)
- `hdl/little64_cores/special_registers.py` — shared special-register interface definitions only (no executable register-bank logic)
- `hdl/little64_cores/core.py` — compatibility export for the current default core variant
- `hdl/little64_cores/basic/core.py` — current single-issue multi-cycle core FSM with fetch, GP ALU, jumps, and basic LSU execution
- `hdl/little64_cores/basic/helpers.py` — Basic-core-local decode and ALU helper logic
- `hdl/little64_cores/basic/tlb.py` — Basic-core-local TLB implementation
- `hdl/little64_cores/basic/special_registers.py` — Basic-core-local special-register implementation
- `hdl/little64_cores/v2/core.py` — V2 core with fetch, execute, privilege/MMU, and cache-topology support behind the shared external interface
- `hdl/little64_cores/v2/helpers.py` — V2-core-local decode, ALU, and MMU helper logic
- `hdl/little64_cores/v2/tlb.py` — V2-core-local TLB implementation
- `hdl/little64_cores/v2/special_registers.py` — V2-core-local special-register implementation
- `hdl/little64_cores/v2/cache.py` — small direct-mapped cache-line store used by the V2 data-side cache path
- `hdl/little64_cores/v2/frontend.py` — 64-bit fetch-line frontend that extracts 16-bit instructions for the V2 pipeline
- `hdl/little64_cores/v2/lsu.py` — V2 load/store unit handling aligned and split 64-bit Wishbone accesses
- `hdl/little64_cores/v2/decode.py` — V2 decode helpers used by the pipeline bring-up path
- `hdl/little64_cores/v2/__init__.py` — V2-local package export surface for the core, pipeline state, and V2-owned helper blocks
- `hdl/little64_cores/v3/core.py` — experimental single-issue pipelined V3 bring-up path, currently covering fetch/decode/execute, fetch/data MMU/TLB translation, LSU-backed load/store/push/pop and `LLR`/`SCR` sequencing, the shared `none` / `unified` / `split` cache-topology contract, paged interrupt-vector lookup, maskable IRQ delivery, precise synchronous trap entry, `IRET`, and memory-result control-flow redirects behind the shared external interface
- `hdl/little64_cores/v3/helpers.py` — V3-core-local decode, ALU, and MMU helper logic
- `hdl/little64_cores/v3/tlb.py` — V3-core-local TLB implementation
- `hdl/little64_cores/v3/special_registers.py` — V3-core-local special-register implementation
- `hdl/little64_cores/v3/cache.py` — V3-local data cache implementation owned by the V3 subtree
- `hdl/little64_cores/v3/frontend.py` — V3-local fetch frontend implementation owned by the V3 subtree
- `hdl/little64_cores/v3/lsu.py` — V3-local load/store unit implementation owned by the V3 subtree
- `hdl/little64_cores/v3/__init__.py` — V3-local package export surface for the core, pipeline state, and V3-owned helper blocks
- `hdl/little64_cores/v3/` — experimental V3 subtree for the next fully pipelined core; it now participates in the default shared ISA/program/core-smoke/trap/MMIO regression matrix, and also exposes LiteX-facing `standard-v3*` CPU variants plus the shared `none` / `unified` / `split` cache-topology surface
- `hdl/little64_cores/v3/state.py` — V3-visible pipeline state enum used for debug/status reporting
- `hdl/little64_cores/v3/bundles.py` — V3 stage-local signal bundle classes for decode, execute, memory, and retire organization
- `hdl/little64_cores/v3/decode_stage.py` — decode-stage register read, bypass, and conservative hazard detection
- `hdl/little64_cores/v3/execute_stage.py` — execute-stage instruction semantics and memory-operation generation
- `hdl/little64_cores/v3/memory_stage.py` — LSU-backed memory-stage completion and chained push/pop sequencing
- `hdl/little64_cores/v3/retire_stage.py` — retire-stage decode of writeback, commit, halt, trap, and CPU-control actions
- `hdl/little64_cores/v4/core.py` — experimental V4 in-order pipelined core with v4-local frontend/LSU/decode and shared V3 stage logic reuse where appropriate
- `hdl/little64_cores/v4/frontend.py` — V4-local fetch frontend implementation owned by the V4 subtree
- `hdl/little64_cores/v4/lsu.py` — V4-local load/store unit implementation owned by the V4 subtree
- `hdl/little64_cores/v4/decode_stage.py` — V4-local decode and hazard handling with branch-prediction wiring
- `hdl/little64_cores/v4/predictor.py` — V4 branch-prediction policies
- `hdl/little64_cores/v4/bundles.py` — V4 stage-local signal bundle classes
- `hdl/little64_cores/v4/__init__.py` — V4-local package export surface
- `hdl/little64_cores/variants.py` — shared core-variant and cache-topology selection helpers used by the LiteX-facing path
- `hdl/little64_cores/litex.py` — LiteX-facing profile, named target and boot-source descriptors, wrapper shim, and generic CPU export top
- `hdl/little64_cores/litex_cpu.py` — real LiteX CPU plugin and raw Little64 data-bus alignment bridge
- `hdl/little64_cores/litex_linux_boot.py` — Linux ELF flattening and SPI-flash image packing helpers for the LiteX path
- `hdl/little64_cores/litex_soc.py` — minimal LiteX simulation SoC wrapper and Linux DTS generator
- `hdl/tests/` — Python simulation and unit tests for unit and ISA coverage
	- shared HDL suites default to the current `v4,v2,v3` matrix and can be run against `basic`, `v2`, `v3`, `v4`, or `all` with `./.venv/bin/python -m pytest hdl/tests --core-variants default|basic|v2|v3|v4|all`
	- shared architectural suites now use capability markers and a test-only core adapter layer so variant-specific startup details and component factories stay out of the shared test bodies
	- includes shared generated ISA/program/MMIO coverage, shared unaligned-access coverage, shared trap/atomic/core-smoke coverage, explicit V3 MMU/trap regression coverage, and V2/V3 cache-topology regression tests
- `little64 hdl flash-image` — build a bootable SPI-flash image containing stage-0, Linux, and a DTB
- `little64 hdl export-cpu` — export the generic LiteX CPU wrapper to Verilog
- `little64 hdl wrappers-llvm` — emit LiteX-compatible triple-prefixed LLVM tool wrappers for the repo toolchain
- `little64 hdl dts-linux` — emit a Linux DTS for the LiteX simulation SoC shape

The current Python/Amaranth simulation path is appropriate for unit and ISA coverage but is too slow for practical full-Linux boot validation. Linux-on-HDL boot validation now runs through LiteX's own simulation toolchain via `little64 hdl sim-litex`.

## Arty Hardware Build Path

The repo now also has a Python-first Arty hardware build/programming entrypoint
for real LiteX/Vivado workflows:

- `little64 hdl arty-build`

The current scope is hardware project generation, bitstream generation, and
direct board programming for the Digilent Arty A7-35T. It is intentionally
separate from the existing simulation-first Linux boot helpers, but each build
now also cleans and regenerates staged SD boot artifacts under
`builddir/hdl-litex-arty/boot/`.

The Arty path currently:

1. reuses the existing Little64 LiteX target metadata for the Arty SDRAM-backed layout,
2. instantiates a real Arty platform through `litex-boards`,
3. uses the onboard DDR3 via LiteDRAM,
4. can optionally expose the onboard SPI flash as a LiteSPI controller,
5. wires an external SD card through either the native 4-bit LiteSDCard path or the existing SPI-mode SD controller,
6. defaults to an Arduino-style SDIO breakout preset on `ck_io34..40`, while still supporting the older SPI Arduino preset on `ck_io30..33` and PMOD-based mappings,
7. stages a rebuilt DTS, DTB, SD bootrom image, and SD card image alongside the hardware build outputs,
8. can optionally program the resulting artifacts over JTAG or into the board's configuration flash.

The stage-0 source at `target/c_boot/litex_sd_boot.c` now supports both the
native LiteSDCard bootrom-first flow and the Arty SPI-mode SD path from the
same C file. The generated register header selects the backend at build time,
so the Arty helper now compiles that same source against either the hardware
native LiteSDCard CSR layout or the `spisdcard` CSR layout and preloads the
result into the integrated boot ROM.
That shared stage-0 now also consumes a small `BOOT.CRC` manifest from the
FAT32 boot partition, verifies the loaded kernel image and DTB CRCs while it
copies them from SD, and then rechecks the resulting SDRAM contents before
handoff so SD-transfer corruption and post-write RAM corruption fail before the
kernel jump.

The Arty helper also post-processes the generated top-level Verilog to tie off
known optional 7-series primitive ports that LiteX/LiteDRAM leave omitted,
which cuts down Vivado synthesis noise without changing the emitted logic.

The Arty hardware SoC now also uses some of the board LEDs for direct CPU
bring-up status without requiring any software support:

- mono LED 0 = `halted` (used as the current stopped indicator)
- mono LED 1 = `locked_up`
- mono LED 2 = pulse-stretched instruction-bus request activity
- mono LED 3 = pulse-stretched data-bus request activity
- RGB LED 0 red = pulse-stretched store activity
- RGB LED 0 green = running heartbeat (off when halted or locked up)
- RGB LED 0 blue = pulse-stretched interrupt-pending indication
- RGB LED 1 red = pulse-stretched native SD CMD output transitions
- RGB LED 1 green = pulse-stretched native SD CMD output-enable transitions
- RGB LED 1 blue = pulse-stretched native SD CMD input transitions observed while CMD is released
- remaining RGB LEDs are held off for deterministic behavior

The current Arty wiring drives the RGB channels as active-high. If the mono
LEDs behave correctly but the RGB LEDs all come up bright or the "off" LEDs
show white, the RGB polarity assumption in `hdl/little64_cores/litex_arty.py`
is the first place to check.

This is intentionally Arty-local debug wiring in `hdl/little64_cores/litex_arty.py`.
The first pass reuses the existing LiteX CPU `halted` and `locked_up` outputs
instead of introducing a separate STOP-only status signal through the shared
LiteX wrapper hierarchy.

Current limitation:

- Kernel-side SPI-SD integration is still separate from stage-0. The bootrom can now load the kernel and DTB from SPI-mode SD on Arty builds, but the generated Linux DT path does not yet describe the SPI-SD storage path as a kernel rootfs device. The native 4-bit Arty path reuses the standard LiteX MMC/DTS contract instead.
- The native Arty bootrom path currently forces filesystem block reads back to 1-bit mode after SD init. Hardware bring-up confirmed that card init, SCR reads, and bus-width switching work, but the current 4-bit bulk-read path can return shifted block payload bytes during FAT/kernel/DTB reads. Stage-0 restores the SD PHY width setting to 4-bit again before handing off to Linux.
- The simulation/emulator bootrom-first flow still uses the native LiteSDCard backend from the same source file.

For repeated hardware testing against an already partitioned SD card, use `little64 sd update --device /dev/sdX` after regenerating the staged Arty SD image under `builddir/hdl-litex-arty/boot/`. That rewrites only the boot partition by default, and rewrites the rootfs partition only when `--update-rootfs` or `--rootfs-image PATH` is requested.

Typical usage:

```bash
./.venv/bin/little64 hdl arty-build
./.venv/bin/little64 hdl arty-build --generate-only
./.venv/bin/little64 hdl arty-build --sdcard-mode native
./.venv/bin/little64 hdl arty-build --sdcard-mode spi
./.venv/bin/little64 hdl arty-build --vivado-stop-after synthesis
./.venv/bin/little64 hdl arty-build --vivado-stop-after implementation
./.venv/bin/little64 hdl arty-build --sdcard-mode spi --sdcard-connector pmodd --sdcard-adapter digilent
./.venv/bin/little64 hdl arty-build --program volatile
./.venv/bin/little64 hdl arty-build --program flash
./.venv/bin/little64 hdl arty-build --program-only --program volatile
```

Programming notes:

- `--program volatile` loads the generated `.bit` into FPGA SRAM for the current power cycle.
- `--program flash` writes the generated configuration `.bin` into the onboard SPI flash for persistent boot.
- `--program-only` reuses existing artifacts from the selected output directory instead of rebuilding them.
- `--vivado-stop-after synthesis` stops after synthesis reports and the `_synth.dcp` checkpoint, which is useful when triaging synthesis warnings without paying for implementation.
- `--vivado-stop-after implementation` runs through place/route and reports, writes the `_route.dcp` checkpoint, and skips final bitstream generation.
- `--programmer auto|vivado|openocd` selects the programming backend; `auto` prefers Vivado when available.
- Vivado-backed flash programming defaults to cfgmem part `s25fl128l-spi-x1_x2_x4`, matching the Arty A7-35T flash device used by the current LiteSPI integration.

The default Arduino preset now resolves the external Adafruit 4-bit SDIO
breakout's physical header order to the real Arty FPGA pins behind the board's
Arduino-style header:

- `CLK` on `IO34` -> `R16`
- `D0` on `IO35` -> `N16`
- `CMD` on `IO36` -> `N14`
- `D3` on `IO37` -> `U17`
- `D1` on `IO38` -> `T18`
- `D2` on `IO39` -> `R18`
- `DET` on `IO40` -> `P18` (reserved for card-detect; omitted from the active LiteSDCard pad contract when unused)

That ordering matches the Adafruit breakout's mixed SPI/SDIO header
silkscreen, where the SDIO-capable pins appear physically as `CLK, D0, CMD,
D3, D1, DAT2, DET`, while leaving the older SPI wiring on `IO30..33` free so
both modules can remain connected for hardware testing.

The explicit Arduino SPI preset remains available when you select
`--sdcard-mode spi`:

- `CS` on `IO30` -> `R11`
- `MOSI` on `IO31` -> `R13`
- `SCK` on `IO32` -> `R15`
- `MISO` on `IO33` -> `P15`

Use `--sdcard-*-pin` overrides when you need an explicit custom wiring instead
of the built-in Arduino or PMOD conventions. Native mode accepts
`--sdcard-cmd-pin`, `--sdcard-d0-pin`, `--sdcard-d1-pin`, `--sdcard-d2-pin`,
`--sdcard-d3-pin`, and `--sdcard-det-pin`; SPI mode keeps the existing
`--sdcard-mosi-pin`, `--sdcard-miso-pin`, and `--sdcard-cs-pin` overrides.

The V2 path now executes the shared ALU, jump, and LSU subsets, including register-form and PC-relative loads/stores, stack push/pop paths, load-linked/store-conditional sequencing, and split unaligned accesses on the 64-bit Wishbone bus. It now also performs privileged trap entry, Sv39-style page walking for fetch/data/vector accesses, and data-side cache-line reuse behind the `none` / `unified` / `split` cache-topology surface. The LiteX-facing delivery path now exposes those choices through CPU variants, and the Linux boot export/smoke helpers can select non-default V2 configurations. The V2 HDL regression matrix now covers same-line instruction invalidation, paged interrupt-vector fetch, and core trap/MMU fault cases in addition to the shared ISA and memory subsets.

The V3 path now shares the same cache-topology contract as V2 for the current 4-line data-cache implementation: `none` bypasses the cache entirely, `unified` updates the current fetch line on same-line stores, and `split` invalidates that fetch line instead. The LiteX-facing path now exposes explicit `standard-v3`, `standard-v3-none`, `standard-v3-unified`, and `standard-v3-split` CPU variants. The default LiteX `standard` variant now uses V3; use `standard-v2` to target V2 explicitly.

## Linux Boot Smoke

The Linux boot smoke is the practical full-system validation path for the HDL core. It runs through LiteX's own simulation toolchain via the `little64 hdl sim-litex` wrapper described in the next section. The previous repo-local Verilator harness has been retired.

## Native LiteX Simulation Flow

The repo now also has a LiteX-native Linux smoke wrapper that uses LiteX's own
simulation toolchain instead of the repo-local custom Verilator harness.

The LiteX configuration layer now also carries named target descriptors such as
`sim-flash`, `sim-bootrom`, and `arty-a7-35`. These currently drive SoC
metadata and the default reset-source selection. The active native simulation
and smoke flows remain SPI-flash-first by default while the internal boot-ROM
migration is wired through stage-0 and artifact generation.

Run it with:

```bash
./.venv/bin/little64 kernel build --machine litex vmlinuz -j1
./.venv/bin/little64 hdl sim-litex
```

This wrapper:

1. regenerates the LiteX simulation DTS and DTB,
2. rebuilds either the SPI-flash image containing stage-0, the kernel, and the DTB or, with `--with-sdcard`, a SPI-flash stage-0 image plus a raw SD card image,
3. instantiates the existing `Little64LiteXSimSoC` with the matching flash image and either the native LiteSDCard path or an Arty-like SPI SD controller path,
4. asks LiteX's native simulation builder to generate and compile the simulator,
5. runs the resulting `Vsim` binary and watches the serial stream for the required boot markers.

The Little64 LiteX SoC now reserves the canonical CSR pages for the SD, SDRAM,
SPI-flash, and UART blocks instead of relying on LiteX's incidental module-add
order. That keeps the generated DTS, stage-0 headers, and emulator-facing
LiteX-compatible map stable across optional-feature toggles; for example, the
SD-capable layouts keep the documented `sdcard_*`, `sdram`, `spiflash_core`,
and `uart` CSR windows at `0xF0000800`, `0xF0003000`, `0xF0003800`, and
`0xF0004000` respectively whenever those blocks are present.

The DTS generator now keeps a small sidecar cache next to each output DTS and
skips rebuilding when the requested arguments and relevant `hdl/little64_cores/*.py`
inputs are unchanged. Current callers also skip `dtc` when the cached DTS file
mtime has not advanced.

Use this path when you want to validate the Little64 LiteX integration through
LiteX's own simulator plumbing rather than the standalone custom harness.

Useful options:

| Option | Meaning |
|---|---|
| `--build-only` | Build the LiteX simulator and flash artifacts without running them |
| `--run-only` | Reuse an existing LiteX simulator build from the output directory |
| `--with-sdcard` | Build the SD-capable stage-0 flow and stage `sdcard.img` into the LiteX simulator run directory |
| `--sdcard-mode native|spi` | Select the SD backend when `--with-sdcard` is enabled. `native` keeps the existing LiteSDCard simulation path. `spi` switches to an Arty-like SPI SD controller and a pin-level SPI card model. |
| `--rootfs-image PATH` | Optional ext4 rootfs override for the second SD partition when `--with-sdcard` is enabled; when omitted the SD artifact builder regenerates the default init.S-based rootfs |
| `--cpu-variant NAME` | Select the LiteX CPU variant. `standard` now defaults to the V2 core, `standard-basic` keeps the legacy core, `standard-v2*` remains available for explicit V2 selection, and `standard-v3`, `standard-v3-none`, `standard-v3-unified`, and `standard-v3-split` select the experimental V3 forms. |
| `--timeout-seconds N` | Stop waiting after `N` wall-clock seconds if the boot markers never appear |
| `--require TEXT` | Replace the default success markers with an exact custom marker list |
| `--extra-require TEXT` | Add extra serial markers on top of the default success markers |
| `--jobs N` | Limit LiteX's Verilator compile parallelism |
| `--threads N` | Set LiteX Verilator simulation thread count |

The default output directory for this path is `builddir/hdl-litex-linux-boot/`.

The SPI SD simulation mode is intended specifically for bootrom-stage debugging against the Arty-style SPI controller path. It currently requires `--with-sdram` and defaults to watching for `stage0: sdcard ready (spi)` rather than a Linux banner, because the kernel-side SPI-SD/rootfs integration remains separate from the bootrom-only SPI path.
With `--with-sdcard`, the wrapper uses `builddir/hdl-litex-linux-boot-sdcard/`
instead so SPI-flash and SD-card simulator builds do not reuse stale gateware.

With `--with-sdcard`, the wrapper also builds `little64-linux-sdcard.img`
under the SD-specific output directory and loads it through a repo-local LiteX
sim module that services LiteSDCard block reads from `sdcard.img` in the
simulator run directory.

The default native LiteX smoke success marker is now the kernel banner:

- `Linux version `

That is late enough to prove that stage-0 has handed off and Linux has started
executing real early boot code, but still earlier than waiting for the later
root-mount panic path. When you need a stricter checkpoint, use repeated
`--require` arguments to replace the default marker set entirely, or add
repeated `--extra-require` arguments to keep the Linux banner while also
requiring earlier or later breadcrumbs such as `stage0: handing off to kernel`.

The repo now carries a local mirror of the LiteSDCard emulator Verilog sources
used by this path. Some `litesdcard` Python package installs omit
`litesdcard/emulator/verilog/`, so the Little64 LiteX SD wrapper falls back to
the repo-local copy when the installed package does not provide those RTL files.

### Prerequisites

Before running the smoke:

```bash
./.venv/bin/little64 kernel build vmlinuz -j1
./.venv/bin/pip install -r requirements-hdl.txt
```

The smoke expects the default LiteX simulation kernel profile. Use `--defconfig <name>` only when you intentionally need to build a separate non-default kernel elsewhere.

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

If neither `vmlinuz` nor `vmlinux`, `verilator`, `dtc`, or the required host headers are missing, the
wrapper exits early with an explicit prerequisite error.

## LiteX Integration Status

The repo now has a real repo-local LiteX CPU plugin path for Little64 rather
than only a generic exported wrapper. The current LiteX support includes:

- a `little64` LiteX CPU plugin that registers dynamically with LiteX,
- automatic generation of LiteX-compatible `little64-unknown-elf-*` LLVM wrappers backed by the repo's `compilers/bin` tools,
- a bridge that converts the core's raw byte-addressed data-bus behavior into
	standard LiteX word-addressed Wishbone transactions, including split accesses
	across 64-bit boundaries,
- a minimal simulation-first LiteX SoC wrapper for SRAM, integrated RAM or
	LiteDRAM-backed main RAM, LiteUART, a Linux-compatible timer block,
	memory-mapped SPI flash, and optional LiteSDCard,
- a SPI-flash boot-image flow that compiles a flash-resident stage-0 loader,
	flattens the Linux PT_LOAD image the same way as the emulator's direct loader,
	places the DTB after the kernel image with the same scratch gap, and jumps with
	the existing Little64 physical-entry contract,
- an SD boot-artifact flow that keeps stage-0 in SPI flash, emits a raw SD card
	image with a fixed MBR and FAT32 boot partition, loads `VMLINUX` and
	`BOOT.DTB` through LiteSDCard, and optionally places a second rootfs image in
	the second partition,
- a Linux DTS generator that emits Little64 CPU and interrupt-controller nodes
	plus LiteUART, the Little64 timer node, the Linux-visible RAM window, and the
	memory-mapped flash node, plus LiteSDCard/MMC nodes when requested.

Generate a baseline DTS with:

```bash
./.venv/bin/little64 hdl dts-linux \
	--output builddir/little64-litex.dts \
	--with-spi-flash \
	--integrated-main-ram-size 0x4000000
```

Build a bootable flash image with:

```bash
./.venv/bin/little64 hdl flash-image \
	--kernel-elf target/linux_port/build-litex/vmlinux \
	--dtb builddir/hdl-verilator-linux-boot/little64-litex-sim.dtb \
	--output builddir/little64-linux-spiflash.bin
```

Build SD-oriented LiteX boot artifacts with:

```bash
./.venv/bin/little64 sd build \
	--machine litex \
	--output-dir builddir/boot-direct-litex
```

Or, for an explicit low-level artifact build:

```bash
./.venv/bin/little64 sd build \
	--kernel-elf target/linux_port/build-litex/arch/little64/boot/vmlinuz \
	--dtb builddir/hdl-litex-linux-boot/little64-litex-sim.dtb \
	--flash-output builddir/little64-sd-stage0-spiflash.bin \
	--sd-output builddir/little64-linux-sdcard.img
```

The machine-aware form resolves the default LiteX boot kernel from `target/linux_port/build-litex/arch/little64/boot/vmlinuz` when available and falls back to `target/linux_port/build-litex/vmlinux`, generates a matching DTS and DTB internally, chooses the default LiteX target contract, and emits the generated DTS, DTB, stage-0 image, and SD image together under the selected output directory.
Native LiteX-targeted SD builds now keep the stage-0 UART base aligned with the generated LiteX CSR layout by default. Use `--emulator-bootrom-uart-layout` only when you are generating artifacts for the emulator's shifted bootrom UART contract rather than for a raw LiteX simulation or hardware SoC.

### LiteX Stage-0 Entry

The LiteX SPI-flash flow now uses a dedicated stage-0 SoC boot entry at
`target/c_boot/litex_spi_boot.c`.

The SD-oriented LiteX flow uses a parallel stage-0 entry at
`target/c_boot/litex_sd_boot.c`. That path now enters from the integrated boot
ROM, performs any generated LiteDRAM/DFII initialization required by the
selected SoC target, initializes LiteSDCard, reads a fixed MBR layout from
sector `0`, mounts the first partition as a simple FAT32 volume with a fixed
short-name lookup, loads `VMLINUX` and `BOOT.DTB`, and then hands off with the
same register contract as the SPI-flash stage-0.

On Arty SPI-mode SD builds, the LiteX SPI CSR path now exposes 32-bit transfer
registers to stage-0 so the boot loader can drain payload data in word-sized
chunks instead of one CSR transaction per byte, and the stage-0 FAT32 loader
now groups contiguous sector runs into SPI multiblock reads while caching FAT
sectors during cluster-chain walks.

Its reset sequence is intentionally minimal:

1. enter from the CPU reset PC in the integrated boot ROM,
2. establish a temporary SRAM-backed boot stack,
3. clear stage-0 `.bss`,
4. run the generated LiteDRAM/DFII init sequence when the selected LiteX target exposes SDRAM,
5. run a small destructive SDRAM read/write sanity test at the base of main RAM when SDRAM is present,
6. initialize LiteSDCard and bring the card to transfer-ready state,
7. read the fixed MBR plus FAT32 boot partition from the SD image,
8. load `VMLINUX` and `BOOT.DTB` from the FAT32 root directory,
9. jump to the kernel physical entry with the existing direct-boot register contract.

The stage-0 loader now emits readable serial status lines while it runs through
the normal LiteUART path. The intent is to make simulator and future FPGA
bring-up failures diagnosable from a plain UART capture. In the normal success
path it reports boot-ROM entry, `.bss` clearing, optional SDRAM init progress,
the SDRAM sanity-test result, SD readiness, the kernel and DTB copy plan with
addresses and sizes, coarse copy progress while `VMLINUX` and `BOOT.DTB` are
being pulled from SD into RAM, and the final kernel handoff. Validation
failures also print a descriptive error line before the CPU stops. On the
SPI-mode SD path, stage-0 now also emits short command breadcrumbs around
`CMD0`, `CMD8`, `ACMD41`, `CMD58`, and `CMD16` so real-hardware bring-up can
distinguish an init-phase stall from a later data-read failure.

On hardware-oriented LiteX targets that expose a programmable `uart_phy` CSR
bank, stage-0 now also disables LiteUART events and programs the PHY tuning
word for `115200` baud before emitting its first status line. The simulation
UART model has no separate PHY CSR, so that write is skipped there.

The handoff contract remains aligned with the emulator's direct Linux boot path:

- `R1` = physical DTB address,
- `R13` = kernel boot stack top,
- `PC` = kernel physical entry point,
- paging disabled, supervisor mode.

The SPI-flash stage-0 now keeps its `.bss` and temporary stack in the LiteX
integrated SRAM window at `0x10000000`, so it no longer depends on a low-RAM
scratch hole ahead of the Linux image.

For the current SD milestone, the on-disk contract is intentionally narrow:

- partition 1 is a FAT32 boot partition,
- `VMLINUX` and `BOOT.DTB` are looked up by fixed short names,
- the stage-0 loader currently expects one sector per cluster and two FATs,
- partition 2 is reserved for a later Linux rootfs and can already be populated
	by `--rootfs-image` in the SD artifact builder and LiteX smoke wrapper.

Emit the LiteX LLVM wrapper tools with:

```bash
./.venv/bin/little64 hdl wrappers-llvm \
	--output-dir builddir/litex-toolchain
```

The current LiteX/Linux-facing memory contract now places Linux-visible main
RAM at physical `0x40000000`, matching the current Little64 LiteX kernel
profiles and their `KERNEL_PHYS_BASE = 0x40000000` assumption. The standalone
SPI-flash stage-0 keeps its own scratch state in integrated SRAM at
`0x10000000`, so the kernel image, DTB placement, and post-handoff boot stack
all live in the high main-RAM window without depending on a reserved low-memory
gap.

The simulation SoC also currently leaves the LiteX SoC controller block disabled.
Under this Python 3.13 environment, LiteX's default controller path is hitting a
CSR auto-naming failure during SoC construction. That issue is specific to the
upstream LiteX controller helper rather than the Little64 CPU plugin or bus
bridge, so the current integration keeps UART, memory, and flash bring-up moving
while leaving the controller block for a follow-up compatibility fix.

The Linux tree now also carries a separate LiteX simulation machine profile at
`target/linux_port/linux/arch/little64/boot/dts/little64-litex-sim.dts` with a
matching `little64_litex_sim_defconfig`. This profile uses LiteUART, the
Little64 timer, and the memory-mapped flash node. The older `little64.dts`
profile remains available for manual emulator-only experiments, but the current
Linux helper and FPGA-oriented flow no longer treat it as a first-class path.

That split is intentional. It gives the LiteX and future FPGA bring-up path a
kernel profile that does not inherit the emulator-only ns16550a UART and PV
block root-disk assumptions.

This is all not final. There will likely be changes to this in the future.

### Meson Integration

The HDL smoke is also wired into the optional HDL Meson subtree as `hdl-linux-boot-smoke`:

```bash
meson test -C builddir-hdl hdl-linux-boot-smoke --print-errorlogs
```

That test simply invokes `little64 hdl sim-litex`, so the same prerequisites and environment variables apply.

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

## Deterministic HDL Performance Benchmark

`hdl/tests/perf_bench.py` runs fixed halting workloads in the HDL harness and
reports median cycles, IPC, and speedup across any number of core variants.
Results are cycle-based and independent of host wall-clock speed.

```bash
# Default: compare v2 and v3 on assembly micro-benchmarks
./.venv/bin/python hdl/tests/perf_bench.py

# All supported variants
./.venv/bin/python hdl/tests/perf_bench.py --variants all

# Single variant (reports metrics only, no speedup table)
./.venv/bin/python hdl/tests/perf_bench.py --variants v3

# Select cache topology (v2/v3: none|unified|split)
./.venv/bin/python hdl/tests/perf_bench.py --variants v3 --cache-topology split

# Sweep all cache topologies in one run
./.venv/bin/python hdl/tests/perf_bench.py --variants v3 --cache-topology all

# Include a compiled CoreMark case (requires CoreMark source)
./.venv/bin/python hdl/tests/perf_bench.py \
    --variants v2,v3 --coremark-src ~/coremark
```

Reported metrics per case and variant:

- **Cycles** — simulated clock cycles until `STOP` (lower is better).
- **IPC** — `commit_count / cycles` (higher is better).
- **CoreMark/MHz** — `iterations × 10⁶ / cycles` (ELF cases only; higher is better).
- **Speedup** — cycle ratio relative to the first variant (baseline).
- **Geomean speedup** — geometric mean of per-case speedups.

**CoreMark support.** Pass `--coremark-src PATH` to a directory containing the
standard CoreMark C sources (`core_main.c`, `core_list_join.c`, etc.). The
script compiles them with the repo's Little-64 LLVM toolchain using the
bare-metal port in `target/coremark_hdl/` and runs the resulting ELF under the
HDL harness via `run_elf_flat` in `shared_program.py`. Use
`--coremark-iterations N` to control the iteration count baked into the binary
(default: 1). Use `--coremark-total-data-size N` to control CoreMark
`TOTAL_DATA_SIZE` at compile time (default: 128, reduced from standard 2000; lower values run much faster
in HDL simulation). Use `--coremark-cycle-cap N` to raise the hard cycle budget
if the benchmark does not halt within the default 5 000 000 cycles.

**Cache topology support.** Use `--cache-topology none|unified|split` to run
the full benchmark suite under a specific cache topology, or
`--cache-topology all` to run all topologies sequentially. This setting applies
to all selected variants in a run and is included in both console and JSON
reports. The `basic` core only supports `--cache-topology none`.
