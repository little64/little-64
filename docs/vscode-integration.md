# VS Code Integration

This document describes the recommended VS Code workflow for Little-64.

## Positioning

- VS Code is the primary editor/build/test/debug orchestrator.
- `little-64-gui` and `little-64-qt` remain runtime debugger/inspection frontends.
- Emulator debug transport is protocol-first (RSP baseline).

## Current Debug Transport Status

Implemented baseline in `little-64-debug`:

- `qSupported`
- `?`
- `c`, `s`, interrupt (`0x03`)
- `g`
- `m`
- `Z0`/`z0`
- LLDB compatibility helpers (`qXfer:features:read:target.xml`, thread queries, `vCont?` variants)

## Build/Test Loop

```bash
meson compile -C builddir
meson test -C builddir --print-errorlogs
```

## Debug Server Loop

```bash
meson compile -C builddir little-64-debug
./builddir/little-64-debug 9000 [optional-image.elf]
```

## LLDB Toolchain Preparation

```bash
cd compilers
ENABLE_LLDB=1 ./build.sh llvm
./bin/lldb --version
./bin/lldb-dap --help
```

## Smoke Workflow (CLI)

```bash
compilers/bin/llvm-mc -triple=little64 -filetype=obj target/asm/debug_smoke.asm -o builddir/debug-smoke.o
compilers/bin/ld.lld builddir/debug-smoke.o -o builddir/debug-smoke.elf
./builddir/little-64-debug 9000 builddir/debug-smoke.elf
compilers/bin/lldb --batch -o "gdb-remote 127.0.0.1:9000" -o "process continue"
```

## VS Code Tasks/Launch Guidance

Recommended task categories:

1. build emulator/debug targets,
2. build test image (`.o`/`.elf`),
3. run debug server in background,
4. attach LLDB DAP session.

Keep launch/task wiring protocol-agnostic where practical so backend improvements do not require UI workflow redesign.

## Known Limitations

- LLDB-native architecture support for Little-64 remains incomplete.
- Emulator virtual breakpoints (`Z0`/`z0`) are the stable path today.

## Update Checklist

When debug transport changes:

- update supported packet list here,
- update integration tests under `tests/host/debug/` when protocol behavior changes,
- run:
  - `meson test -C builddir debug-rsp-integration --print-errorlogs`
  - `meson test -C builddir debug-lldb-remote-smoke --print-errorlogs`
