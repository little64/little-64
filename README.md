# Little-64

Little-64 is a 64-bit ISA project with:

- a C++ emulator/runtime,
- an Amaranth HDL implementation subtree,
- an LLVM-based assembler + custom disassembler/linker toolchain,
- project-runner workflows,
- debug-server support (GDB RSP subset),
- optional ImGui and Qt frontends.

## Cloning

Clone the `llvm-project` submodule as well. There is a wired-up `lily-cc` submodule as well, but I haven't written any working backend for it yet, and to be honest, will be using LLVM mostly anyway.

LLVM is required for the tests as well. Compile it with `bash compilers/build.sh llvm` first. This will take a while and use a lot of RAM.

## Quick Start

### 1) Configure and build

```bash
meson setup builddir
meson compile -C builddir
```

### 2) Run all tests

```bash
meson test -C builddir --print-errorlogs
```

### 3) Run emulator with an image

```bash
./builddir/little-64 <program.bin|program.o|program.elf>
```

## Primary Binaries

| Binary | Purpose |
|---|---|
| `builddir/little-64` | Headless emulator runner |
| `builddir/little-64-debug` | TCP debug server (RSP) |
| `builddir/little-64-disasm` | Disassembler (`.bin` to text) |
| `builddir/little-64-linker` | Object linker |
| `builddir/little-64-run` | `.l64proj` compile/link/run harness |
| `builddir/little-64-gui` | ImGui frontend |
| `builddir/little-64-qt` | Qt frontend (if Qt detected/enabled) |

Assembly to object code uses `compilers/bin/llvm-mc` (see `host/project/llvm_assembler.*`).

## Repository Layout

- `host/` — host-side runtime/tools/frontends (`host/emulator/`, `host/disassembler/`, `host/linker/`, `host/project/`, `host/gui/`, `host/qt/`, ...)
- `hdl/` — Amaranth soft-core CPU implementation and HDL tests
- `target/` — target-side code/images (`target/asm/`, `target/c_boot/`)
- `tests/host/` — host tool/runtime/integration tests
- `tests/target/` — CPU/ISA-focused tests
- `tests/support/` — shared test helpers
- `docs/` — architecture and workflow documentation
- `compilers/` — external compiler ports/toolchains

## Build System Structure

Meson files are modularized by subsystem:

- top-level orchestration: `meson.build`
- per-subsystem build files:
  - `host/emulator/meson.build`
  - `host/disassembler/meson.build`
  - `host/linker/meson.build`
  - `host/project/meson.build`
  - `tests/meson.build`
  - `host/gui/meson.build`
  - `host/qt/meson.build`

## Documentation

Start with `docs/README.md` for the full index.

Key docs:

- `docs/hardware/README.md` — hardware architecture reference and replacement entry point for the old monolithic architecture docs
- `docs/hdl.md` — HDL subsystem scope, layout, and test entry points
- `docs/emulator/README.md` — emulator runtime, boot, and virtual-platform documentation
- `docs/assembly-syntax.md` — LLVM-targeted assembly language notes and compatibility guidance
- `docs/architecture-boundaries.md` — module/API boundaries
- `docs/device-framework.md` — MMIO/device model and extension path
- `docs/vscode-integration.md` — editor/debug workflow integration
- `GUI_DEBUGGER.md` — frontend behavior and usage

## Tooling CLI

All project-specific scripting lives in a single Python package under
`tools/little64/`, exposed as the `little64` console entry
point after `pip install -e tools/little64` into the project `.venv`. Run
`little64 --help` for the full command tree; the top-level groups are:

| Group | Purpose |
|---|---|
| `little64 paths` | Resolve repository root, build directory, compiler bin, Linux build profiles |
| `little64 trace` | Decode, tail, search, stats, and watch binary `.l64t` trace files |
| `little64 rsp` | Start/stop/check the BIOS and Linux direct-boot RSP debug servers |
| `little64 lldb` | Launch an LLDB TUI against a Little64 RSP server |
| `little64 kernel` | Build the Linux kernel, resolve PCs to source, analyze boot-lockup traces |
| `little64 boot` | Direct-boot a Little64 kernel ELF; sample and cluster fast-boot outcomes |
| `little64 sd` | Build the bootrom stage-0 and SD card image used by the LiteX flows, or update only the partitions of an existing SD card |
| `little64 rootfs` | Build minimal init-based or mlibc-based ext4 rootfs images |
| `little64 bios` | Build and run the C-BIOS ELF under the emulator |
| `little64 dev` | Developer scaffolding (e.g. new MMIO device skeletons) |
| `little64 hdl` | HDL/LiteX bitstream, simulation, and Verilog-export helpers |

Legacy shell wrappers under `target/` and `host/tools/` have been retired;
`tests/host/test_no_shell_wrappers.py` enforces that they do not return.

## Linux Direct Boot

The Linux bring-up flow lives under `target/linux_port/` and is intentionally outside the Meson graph.

Typical direct-boot flow with the LiteX SD-capable machine:

```bash
./.venv/bin/little64 kernel build vmlinuz -j1
little64 rootfs build
little64 boot run
```

The default direct-boot rootfs image is `target/linux_port/rootfs/build/rootfs.ext4`.
For the LiteX machine, `little64 boot run` regenerates a minimal ext4 SD rootfs from `target/linux_port/rootfs/init.S` unless you override it with `--rootfs PATH` or disable it with `--no-rootfs`.
The boot helper prefers `target/linux_port/build-litex/arch/little64/boot/vmlinuz` when it exists and falls back to `target/linux_port/build-litex/vmlinux`; symbol-oriented helpers still use `vmlinux`.
Use `little64 boot run --no-rootfs` to boot the selected machine profile without attaching a rootfs image.
Use `little64 boot run --mode=smoke` for the lower-overhead no-event-capture smoke path.
Use `little64 boot run --mode=rsp` to launch the direct-boot RSP debug server.

The Linux build helper defaults to `little64_litex_sim_defconfig`. To switch away from that default,
use `--defconfig <name>` or `LITTLE64_LINUX_DEFCONFIG=<name>`, for example:

```bash
./.venv/bin/little64 kernel build vmlinux -j1
# or
./.venv/bin/little64 kernel build --defconfig <name> vmlinux -j1
```

The default LiteX profile builds into a stable directory, and any explicit defconfig uses its own profile-derived directory:

- `target/linux_port/build-litex/` for `little64_litex_sim_defconfig`

Explicit defconfigs build into `target/linux_port/build-<defconfig>/` by default so they do not overwrite the canonical LiteX directory.

## LiteX Linux Boot Helpers

The LiteX-oriented Linux boot helpers are exposed as `little64` CLI subcommands; stage-0 C sources live under `target/c_boot/`.
The current flow is:

```bash
./.venv/bin/little64 sd build --machine litex --output-dir builddir/boot-direct-litex
./.venv/bin/little64 hdl wrappers-llvm --output-dir builddir/litex-toolchain
./.venv/bin/little64 hdl dts-linux --output builddir/little64-litex.dts --with-spi-flash
./.venv/bin/little64 hdl flash-image --kernel-elf target/linux_port/build-litex/vmlinux --dtb builddir/hdl-verilator-linux-boot/little64-litex-sim.dtb --output builddir/little64-linux-spiflash.bin
./.venv/bin/little64 sd build --kernel-elf target/linux_port/build-litex/arch/little64/boot/vmlinuz --dtb builddir/hdl-verilator-linux-boot/little64-litex-sim.dtb --flash-output builddir/little64-sd-stage0-spiflash.bin --sd-output builddir/little64-linux-sdcard.img
```

For a LiteX-native simulation run, use:

```bash
./.venv/bin/little64 kernel build vmlinuz -j1
./.venv/bin/little64 hdl sim-litex
```

This path uses LiteX's own simulation builder and `SimPlatform` plumbing rather than the repo-local custom Linux-on-Verilator harness.
It also requires the host development headers for `json-c` and `libevent` in addition to the Python packages from `requirements-hdl.txt`.
`little64 hdl sim-litex` now prefers `target/linux_port/build-litex/arch/little64/boot/vmlinuz` when it exists and falls back to `target/linux_port/build-litex/vmlinux`.

The generated flash image contains a dedicated stage-0 entry at
`target/c_boot/litex_spi_boot.c` that establishes a temporary low-RAM stack,
clears its own `.bss`, copies kernel plus DTB into RAM, and then jumps into the
normal Little64 Linux physical-entry contract.

The SD boot helper at `little64 sd build` now supports two modes.
Machine-aware mode:
`./.venv/bin/little64 sd build --machine litex --output-dir builddir/boot-direct-litex`
This resolves the default LiteX kernel from `target/linux_port/build-litex/`, generates matching DTS and DTB artifacts internally, chooses the stage-0 image shape from the selected boot source, and writes the stage-0 plus SD image into the output directory.
Explicit mode:
pass `--kernel-elf`, `--dtb`, and explicit output paths when you need full control over the inputs or want to build a non-default target shape.
Both modes regenerate the minimal ext4 rootfs from `target/linux_port/rootfs/init.S` unless `--no-rootfs` or `--rootfs-image PATH` is used.

To push a staged SD image onto an already partitioned test card without rewriting the whole raw device, use:

```bash
./.venv/bin/little64 sd update --device /dev/sdX
./.venv/bin/little64 sd update --device /dev/sdX --update-rootfs
./.venv/bin/little64 sd update --device /dev/sdX --sd-image builddir/hdl-litex-arty/boot/little64_arty_a7_35_sdcard.img
```

`little64 sd update` rewrites partition 1 from the staged SD image and leaves partition 2 alone unless `--update-rootfs` or `--rootfs-image PATH` is supplied.

For the canonical Little64 LiteX helper flows (`little64 boot run`, `little64 sd build --machine litex`, and `little64 hdl sim-litex --with-sdcard`), the CSR window layout is now intentionally fixed rather than add-order-dependent:

- LiteSDCard reader `0xF0000800`
- LiteSDCard core `0xF0001000`
- LiteSDCard IRQ `0xF0001800`
- LiteSDCard writer `0xF0002000`
- LiteSDCard PHY `0xF0002800`
- LiteDRAM DFII / SDRAM CSR `0xF0003000`
- LiteSPI flash CSR `0xF0003800` when present
- LiteUART `0xF0004000`

That fixed map is the contract shared by the native LiteX SoC, the generated DTS,
the stage-0 SD boot headers, and the emulator's default `--machine=litex`
bootrom-first flow. The older explicit manual emulator mode
`--boot-mode=litex-flash --disk` remains a separate compatibility path and still
uses its legacy flash-layout UART slot at `0xF0003800`; do not treat that
manual mode as the source of truth for the canonical LiteX helper contract.

The Linux tree still carries two separate built-in machine profiles:

- `little64-litex-sim` / `little64_litex_sim_defconfig` is the LiteX simulation profile with LiteUART, the Little64 timer, and memory-mapped flash, and is now the default Linux bring-up profile.
- `little64` / `little64_defconfig` remains as a legacy emulator-oriented profile for manual experiments, but the helper scripts no longer special-case it.

The LiteX profile is still simulation-first. It is the correct base for future FPGA work because it matches the helper flow's LiteUART, timer, flash, and SD-oriented boot contract, but it is not yet an Arty board-support package.

## Arty Bitstream Build

The repo now also includes a Python-first LiteX/Vivado entrypoint for building
Little64 gateware for the Digilent Arty A7-35T:

```bash
./.venv/bin/pip install -r requirements-hdl.txt
./.venv/bin/little64 hdl arty-build
```

Useful variants:

```bash
./.venv/bin/little64 hdl arty-build --generate-only
./.venv/bin/little64 hdl arty-build --sdcard-mode native
./.venv/bin/little64 hdl arty-build --sdcard-mode spi
./.venv/bin/little64 hdl arty-build --sdcard-mode spi --sdcard-connector pmodd --sdcard-adapter digilent
./.venv/bin/little64 hdl arty-build --with-spi-flash
./.venv/bin/little64 hdl arty-build --program volatile
./.venv/bin/little64 hdl arty-build --program flash
./.venv/bin/little64 hdl arty-build --program-only --program volatile
```

The helper now also supports direct board programming. `--program volatile`
loads the generated `.bit` over JTAG for a temporary session, while
`--program flash` writes the generated configuration `.bin` into the onboard
SPI flash for persistent boot. `--program-only` skips the build and reuses the
existing artifacts under `builddir/hdl-litex-arty/gateware/`.

Each non-`--program-only` Arty build now also removes stale LiteX `gateware/`,
`software/`, and `boot/` outputs and regenerates the staged SD boot assets
under `builddir/hdl-litex-arty/boot/`, including the SD bootrom built from
`target/c_boot/litex_sd_boot.c`. That same source now builds both the native
LiteSDCard stage-0 used by the simulator/emulator flows and the SPI-mode SD
stage-0 used by the current Arty hardware path, and the Arty helper preloads
the backend-matched build into the integrated boot ROM.

The default Arty SD wiring now targets the Adafruit 4-bit SDIO breakout on
Arduino pins `IO34..40` in the breakout's physical header order `CLK, D0, CMD,
D3, D1, D2, DET`, which leaves the older SPI test wiring on `IO30..33`
available so both modules can stay connected during bring-up. Use
`--sdcard-mode spi` to keep using the older SPI header mapping.

The staged Arty DTS now also includes the Little64 Linux timer block, and the
current hardware helper no longer advertises an unsupported MMC rootfs device
in its default bootargs.

The remaining gap is kernel-side SPI-SD/rootfs integration: the bootrom can
now load the kernel and DTB from SPI-mode SD on Arty builds, but the Linux DT
and rootfs path are still separate follow-up work.

## Toolchain Separation Policy

`compilers/llvm/` and `compilers/lily-cc/` remain intentionally separate to preserve independent local development workflows.

Do not merge or restructure these trees as part of normal project cleanup.

## Documentation Maintenance

When behavior changes, update docs in the same change:

1. Update hardware docs for core ISA changes and emulator docs for implementation-specific behavior changes.
2. Update syntax docs for LLVM assembly behavior changes.
3. Update `CLAUDE.md` when contributor workflows or touched-file rules change.
4. Run `meson test -C builddir --print-errorlogs` before finalizing documentation that includes command examples.

## Clanker warning

LLMs were used when developing this, but mostly for the LLVM port.
LLMs were used in other places as well, but the code was a lot more reviewed there than in the LLVM target.
