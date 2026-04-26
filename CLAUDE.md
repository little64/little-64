# Little-64 — Contributor Notes

This file documents practical update paths and maintenance rules for common project changes.

## Build System

- Build system: Meson
- Build directory: `builddir/`
- Build graph is modularized:
  - `meson.build` (top-level orchestration)
  - subsystem build files in `host/emulator/`, `host/disassembler/`, `host/linker/`, `host/project/`, `tests/`, `host/gui/`, `host/qt/`
  - optional HDL subtree in `hdl/`

## compiler-rt Builtins

- The LLVM build script (`compilers/llvm/build.sh`) cross-builds compiler-rt builtins for Little64 after the main toolchain build.
- Build directory: `compilers/llvm/build-builtins-little64/`
- Output library: `libclang_rt.builtins-little64.a`
- Installed into the clang resource directory (`lib/clang/<version>/lib/` and `lib/clang/<version>/lib/baremetal/`) so the BareMetal driver finds it automatically.
- Also exported alongside `compilers/bin/` at `compilers/lib/clang/<version>/lib/`.
- Architecture registration files:
  - `compiler-rt/cmake/builtin-config-ix.cmake` — `LITTLE64` arch family
  - `compiler-rt/cmake/Modules/AllSupportedArchDefs.cmake` — `LITTLE64` variable
  - `compiler-rt/lib/builtins/CMakeLists.txt` — `little64_SOURCES` set
  - `compiler-rt/lib/builtins/little64/fp_mode.c` — FP rounding mode stubs (no FPU)
- Clang driver integration: Little64 is handled by the BareMetal toolchain (`clang/lib/Driver/ToolChains/BareMetal.cpp`), which defaults to `--rtlib=compiler-rt`.
- The Linux kernel does **not** use this library; it has its own stubs in `arch/little64/lib/`.

## Linux Kernel Build

- Kernel build is the `little64 kernel build` subcommand:
  - Usage: `./.venv/bin/little64 kernel build [--machine litex] [--defconfig <name>] [--build-dir <path>] [target] [make-args...]` where the default target is `vmlinux`.
  - Invokes the Linux kernel `make` target with the Little64 LLVM toolchain from `compilers/bin`.
  - Not part of the Meson graph and is meant for local Linux port experimentation only.
  - Supports the canonical `--machine litex` profile, plus explicit overrides via `--defconfig <name>` and `--build-dir <path>`.
  - Auto-syncs the selected defconfig into a profile-specific build directory when the canonical defconfig changes, the selected defconfig changes, or the build config is missing.
  - Default LiteX profile output directory: `target/linux_port/build-litex/`.
  - Explicit defconfigs build into `target/linux_port/build-<defconfig>/` unless `LITTLE64_LINUX_BUILD_DIR` or `--build-dir` overrides it.
  - Default machine profile is `litex`; use `--defconfig <name>` only when you explicitly need a separate non-default kernel config.
  - Normally passes `-j$(nproc)` to `make` unless a `-j` argument is already provided.
- Optional guarded-clang mode can be enabled to catch backend non-termination/memory blowups:
  - `LITTLE64_CLANG_GUARD=1` enables the `target/linux_port/clang_guard.sh` wrapper.
  - `LITTLE64_CLANG_TIMEOUT_SEC` sets per-clang timeout (default `120`).
  - `LITTLE64_CLANG_MAX_VMEM_KB` sets per-clang virtual memory cap in KB (default `10485760`, ~10 GB).
  - `LITTLE64_CLANG_GUARD_LOG_DIR` sets log directory (default `/tmp/little64-clang-guard`).
- Direct ELF boot helper for first Linux bring-up exists at `little64 boot run`:
  - Default image path: `target/linux_port/build-litex/arch/little64/boot/vmlinuz` when present, otherwise `target/linux_port/build-litex/vmlinux`.
  - Default rootfs path: `target/linux_port/rootfs/build/rootfs.ext4`.
  - Usage: `little64 boot run [--machine litex] [--mode trace|smoke|rsp] [--rootfs PATH | --no-rootfs] [--max-cycles N] [--port N] [optional-path-to-kernel-elf]`.
  - Targets the LiteX machine profile only.
  - Default mode `smoke` launches the lower-overhead direct boot flow without boot-event capture.
  - The `litex` profile generates a bootrom-first LiteX image and launches emulator `--boot-mode=litex-bootrom` so the default path matches the SDRAM-backed hardware-oriented SoC layout.
  - The `litex` profile regenerates a minimal ext4 rootfs from `target/linux_port/rootfs/init.S` for SD partition 2 unless `--rootfs PATH` or `--no-rootfs` overrides it.
  - In `trace` mode it streams full boot events to `/tmp/little64_boot_events.l64t` via `--boot-events-file`.
  - Default file size cap: 500 MB (override with `LITTLE64_BOOT_EVENTS_MAX_MB`).
  - Supports cycle-window tracing: `LITTLE64_TRACE_START_CYCLE=N LITTLE64_TRACE_END_CYCLE=N`.
  - Use `--mode=smoke` for the lower-overhead direct boot flow without boot-event capture or stderr event dumping.
  - Use `--mode=rsp` to launch the direct-boot debug server on TCP port `9000` by default, or override it with `--port N`.
- Minimal Linux rootfs build helper exists at `little64 rootfs build`:
  - Output directory: `target/linux_port/rootfs/build/`.
  - Default image path: `target/linux_port/rootfs/build/rootfs.ext4`.
  - Usage: `little64 rootfs build` or `little64 rootfs build clean`.
  - It builds a minimal `/init` ELF using the Little64 LLVM tools and packs it into an ext4 image used by the LiteX SD boot helpers.
  - The LiteX SD artifact builder reuses this helper when it needs the default SD rootfs payload.
  - This is the main bring-up rootfs path and should remain independent of targeted boot regressions; the dedicated Linux userspace-write smoke test builds its own test-only init/rootfs under `tests/host/boot/`.
- Boot-event analysis is the `little64 kernel analyze-lockup` subcommand:
  - Usage: `./.venv/bin/little64 kernel analyze-lockup --log /tmp/little64_boot_events.l64t [--tail N] [--defconfig <name>] [--elf <path>]`.
  - Reads binary `.l64t` trace files.
- Binary trace decoder is the `little64 trace` subcommand group:
  - Usage: `./.venv/bin/little64 trace decode <file>` to convert binary to text.
  - Usage: `./.venv/bin/little64 trace stats <file>` for trace statistics.
  - Usage: `./.venv/bin/little64 trace tail <file> -n N` for last N events.
  - Usage: `./.venv/bin/little64 trace search <file> --tags TAG --pc 0xADDR` for filtering.
  - Usage: `./.venv/bin/little64 trace watch <file>` for live-tailing (like `tail -f`), survives file recreation between runs.
  - **Important**: Trace files (`.l64t`) are binary and cannot be read directly. Always use `little64 trace` subcommands to inspect them.
- PC-to-source lookup is the `little64 kernel pc2line` subcommand:
  - Default image path: selected profile `vmlinux` under `target/linux_port/build-litex/` or `target/linux_port/build-<defconfig>/`.
  - Usage: `./.venv/bin/little64 kernel pc2line [--defconfig <name>] [--elf <path>] [--context-bytes N] [--no-disasm] <pc>`.
  - It resolves a PC to function/file/line using LLVM tools from `compilers/bin` and can show nearby disassembly.
- Repeated fast-boot outcome sampler exists at `little64 boot sample`:
  - Shell wrapper: `little64 boot sample`.
  - Usage: `little64 boot sample [--runs N] [--max-cycles N] [--rootfs PATH | --no-rootfs] [--kernel PATH] [--output-dir PATH] [--jobs N] [--cpu-list LIST]`.
  - It runs `little64 boot run --mode=smoke` repeatedly by default, stores per-run stdout/stderr logs, and clusters recurring outcomes by normalized serial output plus warning/BUG marker lines.
  - It can run multiple samples concurrently and pins each worker to a distinct CPU from the current affinity set (or `--cpu-list`).
  - Default output directory is under `/tmp/little64-fastboot-samples/<timestamp>/`.
- To override core count or pass custom `make` arguments, add them after the target, for example:
  - `./.venv/bin/little64 kernel build vmlinux -j4`
  - `./.venv/bin/little64 kernel build --defconfig <name> vmlinux LOCALVERSION=-custom CONFIG_DEBUG_INFO=y`
  - `LITTLE64_CLANG_GUARD=1 LITTLE64_CLANG_TIMEOUT_SEC=90 ./.venv/bin/little64 kernel build vmlinux -j4`
  - `LITTLE64_CLANG_GUARD=1 LITTLE64_CLANG_MAX_VMEM_KB=10485760 ./.venv/bin/little64 kernel build --defconfig <name> vmlinux -j1`
- If you have made adjustments to the LLVM toolchain, you **MUST** first clean the Linux build folder:
  - `./.venv/bin/little64 kernel build clean`
  - Do **NOT** use mrproper, use `clean`.

## LiteX Linux Boot Helpers

- LiteX Linux DTS helper: `little64 hdl dts-linux`
- LiteX LLVM wrapper helper: `little64 hdl wrappers-llvm`
- LiteX SPI-flash image helper: `little64 hdl flash-image`
- LiteX Arty hardware bitstream helper: `little64 hdl arty-build`
  - Builds a real LiteX/Vivado hardware project for the Digilent Arty A7-35T and can also program the board.
  - Supports `--program volatile` for JTAG bitstream loads, `--program flash` for persistent configuration-flash writes, and `--program-only` to reuse existing artifacts.
  - Supports `--vivado-stop-after synthesis|implementation|bitstream` to stop after the synth checkpoint, after routed implementation reports/checkpoints, or after full bitstream generation.
  - Uses the repo's Arty wrapper around `litex-boards` and now defaults to the Adafruit native 4-bit SDIO breakout header order on `ck_io34..40` (`CLK, D0, CMD, D3, D1, D2, DET`), while still supporting the older SPI Arduino preset on `ck_io30..33` and PMOD mappings through `--sdcard-mode spi`.
  - Each non-`--program-only` build also cleans stale `gateware/`, `software/`, and `boot/` outputs and regenerates staged SD boot artifacts under `builddir/hdl-litex-arty/boot/`.
  - The staged SD bootrom is built from `target/c_boot/litex_sd_boot.c`, which now supports both the native LiteSDCard and SPI-mode SD backends from the same C source via generated register-header selection.
  - The Arty hardware path now preloads the backend-matched build of that stage-0 into the integrated boot ROM. Linux DT/rootfs support for SPI-mode SD remains separate follow-up work.
- Little64 SD boot artifact helper: `little64 sd build`
  - Builds the bootrom stage-0 image plus the SD card image used by the emulator's `--machine=litex` path and by the bootrom-first LiteX smoke flows.
  - `little64 sd build --machine litex --output-dir <path>` auto-resolves the default LiteX kernel from `target/linux_port/build-litex/`, generates DTS/DTB internally, and emits the generated stage-0 plus SD image under `<path>`.
  - The canonical Little64 LiteX helper contract uses fixed CSR slots: `sdcard_block2mem=0xF0000800`, `sdcard_core=0xF0001000`, `sdcard_irq=0xF0001800`, `sdcard_mem2block=0xF0002000`, `sdcard_phy=0xF0002800`, `sdram=0xF0003000`, optional `spiflash_core=0xF0003800`, and `uart=0xF0004000`.
  - Treat those fixed locations as shared contract across `hdl/little64_cores/litex_soc.py`, generated DTS files, SD stage-0 headers, and the emulator's default `--machine=litex` bootrom-first path. If you intentionally move one, update all of those surfaces in the same change.
  - The explicit manual emulator compatibility path `--boot-mode=litex-flash --disk` is a separate legacy layout and still uses LiteUART at `0xF0003800`; do not copy that compatibility address back into the canonical helper flow.
  - Explicit `--kernel-elf <path> --dtb <path>` inputs remain supported for low-level artifact builds.
  - Pass `--with-sdram` when a simulation target should emit generated LiteDRAM init support instead of the integrated-RAM-only contract.
  - Unless `--no-rootfs` or `--rootfs-image PATH` is passed, it regenerates the default ext4 rootfs from `target/linux_port/rootfs/init.S` and installs it into SD partition 2.
- Partition-only SD update helper: `little64 sd update`
  - Rewrites partition 1 from a staged SD image onto an already partitioned SD card or raw disk image without rewriting the full raw device.
  - Defaults to the staged Arty SD image when present, or accepts an explicit source image via `--sd-image PATH`.
  - Leaves partition 2 unchanged unless `--update-rootfs` or `--rootfs-image PATH` is supplied.
- LiteX-native Linux smoke helper: `little64 hdl sim-litex`
  - Uses LiteX's own simulation builder / `SimPlatform` flow instead of the repo-local custom Verilator harness.
  - Default output directory: `builddir/hdl-litex-linux-boot/`.
  - Supports `--build-only` and `--run-only` for iteration on the generated simulator.
  - Requires host development headers for `json-c` and `libevent` in addition to the Python packages from `requirements-hdl.txt`.
- LiteX SPI-flash stage-0 entry source: `target/c_boot/litex_spi_boot.c`
- LiteX SPI-flash linker script: `target/c_boot/linker_litex_spi_boot.ld`
- The stage-0 entry now establishes a temporary integrated-SRAM stack and clears its own `.bss` before entering C.
- The stage-0 handoff contract to Linux is physical-entry only:
  - `R1 = dtb_phys`
  - `R13 = kernel_boot_stack_top`
  - `PC = kernel_entry_physical`

## HDL Timing Improvement Loop

Use this loop for Arty timing work on any Little64 CPU variant. The goal is to make timing experiments comparable and reversible instead of mixing architectural changes, cleanup, and measurement.

1. Pick one CPU variant and keep the rest of the build shape fixed for that loop.
2. Use a dedicated output directory and build name per experiment so reports and checkpoints do not overwrite another variant's artifacts.
3. Prefer `--vivado-stop-after synthesis` until synthesis metrics and failing-path families are moving in the right direction.
4. Make one structural timing hypothesis per loop. Do not mix unrelated refactors, renames, or behavior changes into the same synthesis comparison.
5. Run the smallest relevant HDL regression slice before synthesis so you do not spend Vivado time on a broken RTL experiment.
6. After each synthesis, capture all of the following before deciding whether the change helped:
   - timing summary (`WNS`, `TNS`, failing endpoints),
   - top failing path families,
   - logic-level distribution,
   - high-fanout nets,
   - hierarchical utilization.
7. Compare path families, not just headline `WNS`. A change that slightly improves `WNS` but creates a much deeper or broader failing family is usually a losing trade.
8. Revert experiments that clearly worsen the dominant family or explode endpoint count, even if they are logically clean and tests still pass.
9. Only move on to implementation/place-route after synthesis has stopped pointing at obviously broken cones.
10. Treat directory layout as a maintenance concern, not a timing tool. Splitting files or subtrees does nothing by itself unless it comes with real RTL divergence.
11. Only duplicate or specialize shared blocks after the reports show that a shared microarchitectural block is actually part of the critical path for that core variant.
12. When specializing for one variant, keep architectural helpers shared where practical and split only timing-sensitive microarchitecture such as frontend, LSU, cache integration, or TLB/update plumbing if the reports justify it.

Recommended Arty synthesis loop:

```bash
./.venv/bin/little64 hdl arty-build \
  --cpu-variant <variant> \
  --output-dir builddir/hdl-litex-arty-<tag> \
  --build-name little64_arty_a7_35_<tag> \
  --vivado-settings /path/to/Vivado/settings64.sh \
  --vivado-stop-after synthesis
```

Recommended post-synthesis checkpoint analysis:

```bash
cd builddir/hdl-litex-arty-<tag>/gateware
vivado -mode tcl <<'EOF'
open_checkpoint little64_arty_a7_35_<tag>_synth.dcp
report_high_fanout_nets -max_nets 30
report_design_analysis -logic_level_distribution -setup -max_paths 30
report_timing -delay_type max -slack_lesser_than 0 -max_paths 20 -input_pins
report_qor_suggestions
report_utilization -hierarchical
close_design
quit
EOF
```

Variant-comparison rules:

- Never compare two variants if they reuse the same output directory or report filenames.
- Keep cache-topology, MMU/TLB enablement, and other major build-time knobs explicit in the experiment notes.
- If you are evaluating whether shared RTL should diverge for one core, first prove that the shared block appears in the dominant failing family. Do not split modules based on code organization preference alone.

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
| `little64 dev new-device` | Scaffold hints/messages when integration path changes |
| `docs/device-framework.md` | Update extension workflow |
| tests (`tests/host/test_devices.cpp`) | Add conformance coverage |

Note: `little64 dev new-device` currently instructs contributors to add new device sources in `host/emulator/meson.build`.

## Test Structure

- Generic test macros: `tests/support/test_harness.hpp`
- CPU-specific helpers: `tests/support/cpu_test_helpers.hpp`
- Backward-compat include shim: `tests/test_harness.hpp`
- Shared HDL pytest suites under `hdl/tests/` default to the V2 core; run `./.venv/bin/python -m pytest hdl/tests --core-variants basic|v2|all` when you need the generic HDL coverage against a specific core or both cores.

When adding CPU tests, prefer including `tests/support/cpu_test_helpers.hpp` directly.

## HDL Snippet Debugging

- For one-off HDL core debugging, prefer an in-process Python snippet over ad-hoc terminal fragments so you can import `shared_program.py`, `test_*` helpers, and inspect `run_program_*` results directly.
- If you use `mcp_pylance_mcp_s_pylanceRunCodeSnippet`, set `workspaceRoot` to the repo root and `workingDirectory` to the repo root as well.
- Standalone snippets do **not** load `hdl/tests/conftest.py`, so you must replicate its path bootstrap before importing `little64` or `shared_program`:

```python
import sys
from pathlib import Path

repo = Path.cwd()
sys.path.insert(0, str(repo / "hdl"))
sys.path.insert(0, str(repo / "hdl/tests"))
```

- After that bootstrap, the usual helpers work as expected, for example:

```python
from little64_cores.config import Little64CoreConfig
from shared_program import run_program_words, encode_ls_reg, encode_gp_imm
```

- Use `run_program_source(...)` or `run_program_words(...)` first when you only need architectural outcomes (`halted`, `locked_up`, `trap_*`, `registers`, `special_registers`, `commit_count`).
- Drop to `amaranth.sim.Simulator(...)` only when you need per-cycle internal signals such as V2 pipeline state, frontend fetch state, or LSU handshakes.
- When reproducing a pytest failure in a snippet, copy the same memory image and helper functions from the failing test module (for example `_write_u64`, `_table_pte`, `_leaf_pte` from `hdl/tests/test_traps.py`) instead of rebuilding the setup from scratch.
- A missing bootstrap typically fails with `ModuleNotFoundError: No module named 'little64'`; fix the import path first before assuming the HDL behavior is wrong.

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

# Optional HDL subtree + HDL tests
meson setup --reconfigure builddir -Dhdl=enabled
meson test -C builddir --suite hdl --print-errorlogs

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
