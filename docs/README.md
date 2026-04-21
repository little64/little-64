# Little-64 Documentation Index

This index is the entry point for project docs.

## Recommended Read Order

1. `../README.md`
2. `hardware/README.md`
3. `emulator/README.md`
4. `assembly-syntax.md`
5. `architecture-boundaries.md`
6. `device-framework.md`
7. `vscode-integration.md`
8. `../GUI_DEBUGGER.md`

## Architecture & Behavior

- `hardware/README.md` — replacement entry point for the hardware architecture reference
- `hdl.md` — HDL subsystem scope, layout, and verification entry points
- `emulator/README.md` — implementation-specific emulator and virtual-platform behavior
- `hardware/migration.md` — section-by-section map from the removed monolithic hardware docs
- `architecture-boundaries.md` — layering and API boundaries
- `device-framework.md` — memory-region/device lifecycle model
- `tracing.md` — binary trace subsystem, CLI flags, environment variables, events

## Authoring & Tooling

- `assembly-syntax.md` — LLVM assembly workflow and compatibility notes
- `vscode-integration.md` — VS Code + RSP workflow
- `qt-frontend.md` — Qt frontend scope and status

## Generated Docs

Build locally (strict mode):

```bash
python3 -m venv .venv-docs
./.venv-docs/bin/pip install -r requirements-docs.txt
./.venv-docs/bin/sphinx-build -n -W -b html docs/sphinx docs/_build/html
```

Alternative entry points:

- Meson target: `meson compile -C builddir docs`
- VS Code task: `little64: docs all`

## Linux Bring-up Helpers

- Kernel build helper: `./.venv/bin/little64 kernel build`
	- Prefer `--machine litex` for the canonical profile, or use `--defconfig <name>` for an explicit override.
	- The default profile is `little64_litex_sim_defconfig`; use `--defconfig <name>` or `LITTLE64_LINUX_DEFCONFIG=<name>` for an explicit override.
	- The default LiteX profile builds into `target/linux_port/build-litex/`, and explicit defconfigs build into `target/linux_port/build-<defconfig>/`.
- Minimal rootfs image builder: `little64 rootfs build`
  - Builds the default ext4 image from `target/linux_port/rootfs/init.S`.
- Canonical direct-boot helper: `little64 boot run`
	- The helper targets the LiteX machine profile only, and default mode is `smoke`.
	- `--machine=litex` builds a matching LiteX DTB, SPI flash stage-0 image, and SD card image, then boots the LiteX kernel profile through the emulator's LiteX SD-compatible flash mode.
	- The default LiteX path also regenerates a minimal ext4 rootfs from `target/linux_port/rootfs/init.S` for SD partition 2 unless `--rootfs PATH` or `--no-rootfs` overrides it.
	- The LiteX machine path also verifies that the selected kernel's adjacent `.config` enables `CONFIG_MMC_LITEX=y`, FAT/MSDOS boot-partition support, and `CONFIG_EXT4_FS=y` for the SD rootfs path, unless `LITTLE64_SKIP_LITEX_KERNEL_CONFIG_CHECK=1` is set.
	- Use `--mode=smoke` for the faster no-event-capture smoke path.
	- Use `--mode=rsp` to launch the direct-boot RSP debug server.
- HDL LiteX-native Linux smoke wrapper: `./.venv/bin/little64 hdl sim-litex`
	- Builds the simulator through LiteX's own simulation flow.
	- See `hdl.md` for the HDL-specific prerequisites, environment overrides, and direct-binary workflow.
- Arty hardware build/program helper: `./.venv/bin/little64 hdl arty-build`
	- Builds the Arty A7-35T gateware, cleans stale LiteX build outputs, regenerates staged SD boot artifacts under `builddir/hdl-litex-arty/boot/`, and can optionally program either the volatile `.bit` image or the persistent configuration-flash `.bin`.
	- `--vivado-stop-after synthesis|implementation|bitstream` can stop the Vivado flow after synthesis, after route/checkpoint generation, or after full bitstream emission.
	- The staged SD bootrom now comes from the shared `target/c_boot/litex_sd_boot.c` source, which builds either the native LiteSDCard or SPI-mode SD backend depending on the selected LiteX CSR layout.
	- The Arty helper now preloads the SPI-mode build into the integrated boot ROM; Linux-side SPI-SD rootfs integration is still separate work.
- LiteX Linux flash-image builder: `./.venv/bin/little64 hdl flash-image`
- SD boot artifact builder used by LiteX smoke and emulator LiteX boots: `./.venv/bin/little64 sd build`
	- When `--rootfs-image` is omitted, it regenerates the default ext4 rootfs from `target/linux_port/rootfs/init.S` and installs it into the second SD partition.
- LiteX LLVM wrapper generator: `./.venv/bin/little64 hdl wrappers-llvm`
- LiteX DTS generator: `./.venv/bin/little64 hdl dts-linux`
	- The Linux tree now also carries a separate built-in LiteX simulation profile via `target/linux_port/linux/arch/little64/boot/dts/little64-litex-sim.dts` and `target/linux_port/linux/arch/little64/configs/little64_litex_sim_defconfig`.
- Dedicated Linux userspace-write smoke: `meson test -C builddir 'boot-linux-userspace-write' --print-errorlogs`
  - Builds its own test-only init payload and rootfs image under `builddir/`, so it does not depend on `target/linux_port/rootfs/init.S`
- Repeated fast-boot sampler and outcome clusterer: `little64 boot sample`
	- Supports parallel workers with `--jobs N` and optional explicit affinity selection via `--cpu-list LIST`

## Active Roadmaps

- `lldb-arch-roadmap.md` — phased plan for LLDB-native Little64 architecture support

## Update Contract

For each behavior change:

- update the relevant file under `hardware/` when core ISA semantics change,
- update the relevant file under `emulator/` when implementation-specific behavior changes,
- update `architecture-boundaries.md` or `device-framework.md` when layering or device-model semantics change,
- update `assembly-syntax.md` if LLVM assembly behavior or compatibility rules changed,
- update command examples in docs if CLI behavior changed,
- keep `CLAUDE.md` synchronized with practical contributor steps.

## Style Rules

1. Prefer "source-of-truth" references to duplicated facts.
2. Keep examples executable against current CLI behavior.
3. Add a short "Update Checklist" section to docs that are likely to drift.
4. Avoid status-heavy prose that can become stale quickly.
