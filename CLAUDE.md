# Little-64 — Contributor Notes

This file documents practical update paths and maintenance rules for common project changes.

## Build System

- Build system: Meson
- Build directory: `builddir/`
- Build graph is modularized:
  - `meson.build` (top-level orchestration)
  - subsystem build files in `host/emulator/`, `host/disassembler/`, `host/linker/`, `host/project/`, `tests/`, `host/gui/`, `host/qt/`

## Temporary Linux Build Script

- A temporary Linux kernel build helper exists at `target/linux_port/build.sh`.
- It invokes the Linux kernel `make` target with the Little64 LLVM toolchain from `compilers/bin`.
- The script is currently not part of the Meson graph and is meant for local Linux port experimentation only.
- It auto-syncs `target/linux_port/linux/arch/little64/configs/little64_defconfig` into `target/linux_port/build/.config` when the canonical defconfig changes or the build config is missing.
- Usage: `target/linux_port/build.sh [target]` where the default target is `vmlinux`.
- The script normally passes `-j$(nproc)` to `make` unless a `-j` argument is already provided.
- Optional guarded-clang mode can be enabled to catch backend non-termination/memory blowups:
  - `LITTLE64_CLANG_GUARD=1` enables `target/linux_port/clang_guard.sh` wrapper.
  - `LITTLE64_CLANG_TIMEOUT_SEC` sets per-clang timeout (default `120`).
  - `LITTLE64_CLANG_MAX_VMEM_KB` sets per-clang virtual memory cap in KB (default `10485760`, ~10 GB).
  - `LITTLE64_CLANG_GUARD_LOG_DIR` sets log directory (default `/tmp/little64-clang-guard`).
- Direct ELF boot helper for first Linux bring-up exists at `target/linux_port/boot_direct.sh`:
  - Default image path: `target/linux_port/build/vmlinux`.
  - Default rootfs path: `target/linux_port/rootfs/build/rootfs.ext2`.
  - Usage: `target/linux_port/boot_direct.sh [--rootfs PATH | --no-rootfs] [optional-path-to-vmlinux]`.
  - It launches the headless emulator in direct mode (`--boot-mode=direct`).
  - It attaches the default PV block rootfs image read-only unless `--no-rootfs` is used.
  - It always streams full boot events to `/tmp/little64_boot_events.l64t` via `--boot-events-file`.
  - It also always enables control flow tracing.
  - Default file size cap: 500 MB (override with `LITTLE64_BOOT_EVENTS_MAX_MB`).
  - Supports cycle-window tracing: `LITTLE64_TRACE_START_CYCLE=N LITTLE64_TRACE_END_CYCLE=N`.
- Lower-overhead smoke helper exists at `target/linux_port/boot_direct_no_event_logging.sh`:
  - Usage: `target/linux_port/boot_direct_no_event_logging.sh [--rootfs PATH | --no-rootfs] [--max-cycles N] [optional-path-to-vmlinux]`.
  - It launches the same direct boot flow without boot-event file capture or stderr event dumping, which makes it the better choice for validating whether the kernel still reaches `/init`.
- Minimal Linux rootfs build helper exists at `target/linux_port/rootfs/build.sh`:
  - Output directory: `target/linux_port/rootfs/build/`.
  - Default image path: `target/linux_port/rootfs/build/rootfs.ext2`.
  - Usage: `target/linux_port/rootfs/build.sh` or `target/linux_port/rootfs/build.sh clean`.
  - It builds a minimal `/init` ELF using the Little64 LLVM tools and packs it into an ext2 image for the PV block device.
  - This is the main bring-up rootfs path and should remain independent of targeted boot regressions; the dedicated Linux userspace-write smoke test builds its own test-only init/rootfs under `tests/host/boot/`.
- Boot-event analysis helper exists at `target/linux_port/analyze_lockup_flow.py`:
  - Usage: `target/linux_port/analyze_lockup_flow.py --log /tmp/little64_boot_events.l64t [--tail N] [--elf <path>]`.
  - Reads binary `.l64t` trace files.
  - The shell wrapper `target/linux_port/analyze_lockup_flow.sh` forwards to the Python analyzer.
- Binary trace decoder exists at `target/linux_port/l64trace.py`:
  - Usage: `l64trace.py decode <file>` to convert binary to text.
  - Usage: `l64trace.py stats <file>` for trace statistics.
  - Usage: `l64trace.py tail <file> -n N` for last N events.
  - Usage: `l64trace.py search <file> --tags TAG --pc 0xADDR` for filtering.
  - Usage: `l64trace.py watch <file>` for live-tailing (like `tail -f`), survives file recreation between runs.
  - **Important**: Trace files (`.l64t`) are binary and cannot be read directly. Always use `l64trace.py` subcommands to inspect them.
- PC-to-source lookup helper for Linux kernel debugging exists at `target/linux_port/pc_to_line.sh`:
  - Default image path: `target/linux_port/build/vmlinux`.
  - Usage: `target/linux_port/pc_to_line.sh [--elf <path>] [--context-bytes N] [--no-disasm] <pc>`.
  - It resolves a PC to function/file/line using LLVM tools from `compilers/bin` and can show nearby disassembly.
- Repeated fast-boot outcome sampler exists at `target/linux_port/sample_fast_boots.py`:
  - Shell wrapper: `target/linux_port/sample_fast_boots.sh`.
  - Usage: `target/linux_port/sample_fast_boots.sh [--runs N] [--max-cycles N] [--rootfs PATH | --no-rootfs] [--kernel PATH] [--output-dir PATH] [--jobs N] [--cpu-list LIST]`.
  - It runs `boot_direct_no_event_logging.sh` repeatedly, stores per-run stdout/stderr logs, and clusters recurring outcomes by normalized serial output plus warning/BUG marker lines.
  - It can run multiple samples concurrently and pins each worker to a distinct CPU from the current affinity set (or `--cpu-list`).
  - Default output directory is under `/tmp/little64-fastboot-samples/<timestamp>/`.
- To override core count or pass custom `make` arguments, add them after the target, for example:
  - `target/linux_port/build.sh vmlinux -j4`
  - `target/linux_port/build.sh vmlinux LOCALVERSION=-custom CONFIG_DEBUG_INFO=y`
  - `LITTLE64_CLANG_GUARD=1 LITTLE64_CLANG_TIMEOUT_SEC=90 target/linux_port/build.sh vmlinux -j4`
  - `LITTLE64_CLANG_GUARD=1 LITTLE64_CLANG_MAX_VMEM_KB=10485760 target/linux_port/build.sh vmlinux -j1`
- If you have made adjustmens to the LLVM toolchain, you **MUST** first clean the Linux build folder:
  - `target/linux_port/build.sh clean`
  - Do **NOT** use mrproper, use `clean`.

## Instruction Change Guide

## LS instructions (formats 00 and 01)

| File | Required change |
|---|---|
| `host/arch/opcodes_ls.def` | Add/update `LITTLE64_LS_OPCODE(...)` entry |
| `host/emulator/cpu.cpp` | Update handling in both `_dispatchLSReg(...)` and `_dispatchLSPCRel(...)` |
| `host/project/llvm_assembler.cpp` | Update only if assembly wrapper/tool invocation behavior changes |
| `host/disassembler/disassembler.cpp` | Update only if text output differs from defaults |
| `docs/hardware/instruction-set.md` | Update the instruction-set hardware chapter plan/reference |
| `docs/assembly-syntax.md` | Update syntax and examples if affected |
| tests | Add/update targeted instruction tests |

LS opcodes are shared between format 00 and 01. Behavior can differ by format and must be validated in both dispatch paths.

## GP instructions (format 11 ALU space)

| File | Required change |
|---|---|
| `host/arch/opcodes_gp.def` | Add/update `LITTLE64_GP_OPCODE(...)` entry |
| `host/emulator/cpu.cpp` | Update `_dispatchGP(...)` |
| `host/project/llvm_assembler.cpp` | Usually unnecessary unless wrapper behavior/toolchain pathing changes |
| `host/disassembler/disassembler.cpp` | Update if text output differs from defaults |
| `docs/hardware/instruction-set.md` | Update the instruction-set hardware chapter plan/reference |
| `docs/assembly-syntax.md` | Update syntax and examples if affected |
| tests | Add/update targeted instruction tests |

## Legacy syntax compatibility

Legacy pseudo-forms used in older tests (`LDI64`, `CALL`, `JAL`, `RET`, textual `PUSH`/`POP`, `MOVE Rn+imm`) are currently rewritten for LLVM assembly in `tests/support/cpu_test_helpers.hpp`.

For compatibility updates:

1. adjust rewrite rules in `tests/support/cpu_test_helpers.hpp`,
2. ensure generated instructions preserve original test semantics,
3. update `docs/assembly-syntax.md` compatibility notes,
4. run full test suite.

## Device Framework Changes

| File | Required change |
|---|---|
| `host/emulator/device.hpp` | Base lifecycle contract (`reset`, `tick`) |
| `host/emulator/machine_config.hpp/.cpp` | Machine map registration path (including interrupt sink wiring) |
| `host/emulator/cpu.cpp` | Runtime wiring if device behavior impacts load/reset/cycle |
| `host/tools/new_device.py` | Scaffold hints/messages when integration path changes |
| `docs/device-framework.md` | Update extension workflow |
| tests (`tests/host/test_devices.cpp`) | Add conformance coverage |

Note: `host/tools/new_device.py` currently instructs contributors to add new device sources in `host/emulator/meson.build`.

## Test Structure

- Generic test macros: `tests/support/test_harness.hpp`
- CPU-specific helpers: `tests/support/cpu_test_helpers.hpp`
- Backward-compat include shim: `tests/test_harness.hpp`

When adding CPU tests, prefer including `tests/support/cpu_test_helpers.hpp` directly.

## Documentation Update Contract

When behavior changes, update docs in the same change:

1. The relevant file under `docs/hardware/` for ISA, privilege, memory, boot, or platform changes.
2. `docs/assembly-syntax.md` for assembler syntax/directive changes.
3. `docs/architecture-boundaries.md` for layering/API changes.
4. `docs/device-framework.md` for machine/device model changes.
5. `docs/tracing.md` for trace subsystem, CLI flags, environment variables, or event changes.
6. `README.md` and `docs/README.md` when command paths or reading order changes.
7. this `CLAUDE.md` when contributor workflow instructions change.

## Verification Commands

```bash
# Reconfigure + build
meson setup --reconfigure builddir
meson compile -C builddir

# Full test suite
meson test -C builddir --print-errorlogs

# Dedicated Linux userspace-write boot smoke
meson test -C builddir 'boot-linux-userspace-write' --print-errorlogs

# LLVM Little64 backend tests (MUST run after LLVM backend changes)
cd compilers && ./build.sh llvm
cd llvm/build && ./bin/llvm-lit -sv test/CodeGen/Little64 test/MC/Little64

# One-liner to run all Little64 LLVM tests
(cd compilers/llvm/build && ./bin/llvm-lit -sv test/CodeGen/Little64 test/MC/Little64)
```

For ISA bring-up via LLVM tools:

```bash
compilers/bin/llvm-mc -triple=little64 -filetype=obj test.asm -o test.o
compilers/bin/ld.lld test.o -o test.elf
compilers/bin/llvm-objdump -d --triple=little64 test.elf
./builddir/little-64 test.elf
```

## RSP Debug Server Quick Check

```bash
meson compile -C builddir little-64-debug
./builddir/little-64-debug 9000 [optional-image.elf]
meson test -C builddir debug-rsp-integration --print-errorlogs
meson test -C builddir debug-lldb-remote-smoke --print-errorlogs
```

## Required Reading

Before answering any questions, planning any tasks or implementing any changes, you are required to read the documentation under `docs/`. If you find code contradicts the documentation, the code is authorative, as previously stated, and you must in your next response message report the contradiction, and how it should be solved.
