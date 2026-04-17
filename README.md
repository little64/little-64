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

## Linux Direct Boot

The Linux bring-up flow lives under `target/linux_port/` and is intentionally outside the Meson graph.

Typical direct-boot flow with the LiteX SD-capable machine:

```bash
target/linux_port/build.sh vmlinux -j1
target/linux_port/rootfs/build.sh
target/linux_port/boot_direct.sh
```

The default direct-boot rootfs image is `target/linux_port/rootfs/build/rootfs.ext4`.
For the LiteX machine, `target/linux_port/boot_direct.sh` now regenerates a minimal ext4 SD rootfs from `target/linux_port/rootfs/init.S` unless you override it with `--rootfs PATH` or disable it with `--no-rootfs`.
Use `target/linux_port/boot_direct.sh --no-rootfs` to boot the selected machine profile without attaching a rootfs image.
Use `target/linux_port/boot_direct.sh --mode=smoke` for the lower-overhead no-event-capture smoke path.
Use `target/linux_port/boot_direct.sh --mode=rsp` to launch the direct-boot RSP debug server.
Use `target/linux_port/build.sh --machine virt vmlinux -j1` plus `target/linux_port/boot_direct.sh --machine virt` when you explicitly want the older emulator-oriented PV-block workflow.

The legacy wrappers `target/linux_port/boot_direct_no_event_logging.sh` and
`target/linux_port/boot_direct_debugserver.sh` remain available as compatibility
entrypoints, but `target/linux_port/boot_direct.sh` is now the canonical CLI.

The Linux build helper now defaults to `little64_litex_sim_defconfig`. To switch machine profiles,
prefer `--machine`, or keep using `LITTLE64_LINUX_DEFCONFIG`, for example:

```bash
target/linux_port/build.sh vmlinux -j1
# or
target/linux_port/build.sh --machine virt vmlinux -j1
# or
LITTLE64_LINUX_DEFCONFIG=little64_defconfig target/linux_port/build.sh vmlinux -j1
```

The known machine profiles build into explicit directories:

- `target/linux_port/build-litex/` for `little64_litex_sim_defconfig`
- `target/linux_port/build-virt/` for `little64_defconfig`

Custom defconfigs still build into `target/linux_port/build-<defconfig>/` by
default so they do not overwrite the named profile directories.

## LiteX Linux Boot Helpers

The LiteX-oriented Linux boot helpers live under `hdl/tools/` and `target/c_boot/`.
The current flow is:

```bash
./.venv/bin/python hdl/tools/generate_litex_llvm_wrappers.py --output-dir builddir/litex-toolchain
./.venv/bin/python hdl/tools/generate_litex_linux_dts.py --output builddir/little64-litex.dts --with-spi-flash
./.venv/bin/python hdl/tools/build_litex_flash_image.py --kernel-elf target/linux_port/build-litex/vmlinux --dtb builddir/hdl-verilator-linux-boot/little64-litex-sim.dtb --output builddir/little64-linux-spiflash.bin
./.venv/bin/python target/linux_port/build_sd_boot_artifacts.py --kernel-elf target/linux_port/build-litex/vmlinux --dtb builddir/hdl-verilator-linux-boot/little64-litex-sim.dtb --flash-output builddir/little64-sd-stage0-spiflash.bin --sd-output builddir/little64-linux-sdcard.img
```

For a LiteX-native simulation run, use:

```bash
target/linux_port/build.sh vmlinux -j1
./.venv/bin/python hdl/tools/run_litex_linux_boot_smoke.py
```

This path uses LiteX's own simulation builder and `SimPlatform` plumbing rather than the repo-local custom Linux-on-Verilator harness.
It also requires the host development headers for `json-c` and `libevent` in addition to the Python packages from `requirements-hdl.txt`.

The generated flash image contains a dedicated stage-0 entry at
`target/c_boot/litex_spi_boot.c` that establishes a temporary low-RAM stack,
clears its own `.bss`, copies kernel plus DTB into RAM, and then jumps into the
normal Little64 Linux physical-entry contract.

The SD boot helper at `target/linux_port/build_sd_boot_artifacts.py` builds the
paired SPI-flash stage-0 image plus SD card image used by both the LiteX-native
smoke path and the emulator's `target/linux_port/boot_direct.sh --machine=litex`
flow. By default it also regenerates the minimal ext4 rootfs from
`target/linux_port/rootfs/init.S` and installs that filesystem into the second
SD partition; `--rootfs-image PATH` remains available as an explicit override.

The Linux tree now has two separate built-in machine profiles:

- `little64` / `little64_defconfig` remains the emulator-oriented virtual machine profile with ns16550a UART and PV block root-disk assumptions.
- `little64-litex-sim` / `little64_litex_sim_defconfig` is the LiteX simulation profile with LiteUART, the Little64 timer, and memory-mapped flash, and is now the default Linux bring-up profile.

The LiteX profile is still simulation-first. It is the correct base for future FPGA work because it stops inheriting the emulator-only UART and PV block setup, but it is not yet an Arty board-support package.

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
