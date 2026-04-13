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
- Minimal rootfs image builder: `target/linux_port/rootfs/build.sh`
- Direct-boot helper with rootfs attachment: `target/linux_port/boot_direct.sh`
- Faster smoke helper without boot-event capture: `target/linux_port/boot_direct_no_event_logging.sh`
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
