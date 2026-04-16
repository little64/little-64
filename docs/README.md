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

- Kernel build helper: `target/linux_port/build.sh`
	- Override the default `little64_defconfig` with `LITTLE64_LINUX_DEFCONFIG=<name>`, for example `little64_litex_sim_defconfig`.
	- Non-default profiles build into `target/linux_port/build-<defconfig>/` by default so they do not overwrite the emulator kernel artifacts under `target/linux_port/build/`.
- Minimal rootfs image builder: `target/linux_port/rootfs/build.sh`
- Canonical direct-boot helper: `target/linux_port/boot_direct.sh`
	- Default mode captures control-flow, MMIO, and boot events.
	- Use `--mode=smoke` for the faster no-event-capture smoke path.
	- Use `--mode=rsp` to launch the direct-boot RSP debug server.
- Compatibility wrappers remain available:
	- `target/linux_port/boot_direct_no_event_logging.sh`
	- `target/linux_port/boot_direct_debugserver.sh`
- HDL LiteX-native Linux smoke wrapper: `./.venv/bin/python hdl/tools/run_litex_linux_boot_smoke.py`
	- Builds the simulator through LiteX's own simulation flow instead of the repo-local custom Verilator harness.
- HDL Verilator Linux smoke wrapper: `./.venv/bin/python hdl/tools/run_verilator_linux_boot_smoke.py`
	- See `hdl.md` for the HDL-specific prerequisites, environment overrides, and direct-binary workflow.
- LiteX Linux flash-image builder: `./.venv/bin/python hdl/tools/build_litex_flash_image.py`
- LiteX LLVM wrapper generator: `./.venv/bin/python hdl/tools/generate_litex_llvm_wrappers.py`
- LiteX DTS generator: `./.venv/bin/python hdl/tools/generate_litex_linux_dts.py`
	- The Linux tree now also carries a separate built-in LiteX simulation profile via `target/linux_port/linux/arch/little64/boot/dts/little64-litex-sim.dts` and `target/linux_port/linux/arch/little64/configs/little64_litex_sim_defconfig`.
- Dedicated Linux userspace-write smoke: `meson test -C builddir 'boot-linux-userspace-write' --print-errorlogs`
  - Builds its own test-only init payload and rootfs image under `builddir/`, so it does not depend on `target/linux_port/rootfs/init.S`
- Repeated fast-boot sampler and outcome clusterer: `target/linux_port/sample_fast_boots.sh`
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
