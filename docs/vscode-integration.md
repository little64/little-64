# VS Code Integration Plan (BIOS/OS Bring-up)

Date: 2026-04-01

This document defines the preferred integration path between Little-64 and VS Code, so future implementation can proceed without re-research.

## Product Position

- VS Code is the primary IDE (editing, navigation, build orchestration).
- `little-64-gui` and `little-64-qt` are debugger/inspection frontends.
- Emulator-side investment should focus on protocol/debug substrate, not embedded IDE functionality.

## Why This Path

1. BIOS/OS work requires repeatable scriptable loops, not editor recreation.
2. Existing IDEs already solve source tooling better than custom in-emulator UIs.
3. Protocol-first debugging supports both GUI and headless/CI workflows.

## Integration Architecture

1. **Edit/Build/Test**
   - VS Code tasks call existing build/test toolchain (`meson`, `llvm-mc`, `clang`, `ld.lld`, project runner).
2. **Debug Transport**
   - Emulator debug server exposes a GDB RSP subset first.
3. **Runtime Backend**
   - Debug server maps protocol commands to shared runtime services (`IEmulatorRuntime`).
4. **Optional Frontends**
   - ImGui/Qt consume the same backend services independently.

## Recommended Protocol Sequence

### Phase A (Now): GDB RSP subset

Implement these packet groups first:

1. Capability/handshake
   - `qSupported`
2. Stop reason/state
   - `?`
3. Execution control
   - `c`, `s`, interrupt byte `0x03`
4. Registers
   - `g` (optionally `p`/`P`)
5. Memory
   - `m` (optionally `M`/`X`)
6. Breakpoints
   - `Z0` / `z0`

Notes:
- Treat both software/hardware breakpoint requests as emulator-managed virtual breakpoints in early versions.
- Start in all-stop semantics; extend later only if needed.

### Phase B (After Stability): Convenience + scale

1. Add additional query packets as required by VS Code/GDB flows.
2. Improve stop replies for richer trap/fault context.
3. Add watchpoints and page-fault-aware event reporting.

### Phase C (Optional): DAP-native adapter

- Consider custom DAP adapter only if RSP path becomes limiting.
- Reuse backend runtime/debug services; do not fork execution logic.

## LLDB Bring-up Plan (Step-by-step)

This section defines a practical LLDB enablement path for Little-64.

### Current State Snapshot

1. LLVM/Clang Little-64 backend exists and is functional.
2. LLDB has no Little-64 architecture integration yet.
3. Current compiler build script does not build `lldb`/`lldb-dap`.

### Track 1 — Fastest Usable Path (LLDB client over GDB RSP)

Goal: get VS Code debugging with `lldb-dap`/LLDB **without** first upstreaming a full LLDB target plugin.

#### Step 1: Build LLDB artifacts in local toolchain

1. Update `compilers/llvm/build.sh`:
   - Add `lldb` to `-DLLVM_ENABLE_PROJECTS`.
   - Build `lldb` and `lldb-dap` targets.
   - Copy `lldb` and `lldb-dap` binaries into `compilers/bin`.
2. Keep this behind a flag initially (example: `ENABLE_LLDB=1`) if build time is a concern.

Validation gate:
1. `compilers/bin/lldb --version` runs.
2. `compilers/bin/lldb-dap --help` runs.

#### Step 2: Stabilize emulator debug server baseline for LLDB usage

1. Ensure RSP server supports the minimum packet set LLDB expects for single-thread all-stop debugging:
   - `qSupported`, `?`, `c`, `s`, interrupt `0x03`, `g`, `m`, `Z0`/`z0`.
2. Return deterministic stop replies for breakpoints, single-step, and explicit interrupt.
3. Keep protocol behavior strict and predictable (no partial/ambiguous replies).

Validation gate:
1. `lldb` can connect via `gdb-remote` and continue/step.
2. Register and memory reads work repeatedly in the same session.

#### Step 3: Provide register schema to LLDB via target XML

1. Expose `qXfer:features:read` with `target.xml`.
2. Describe all architectural registers with correct sizes and numbering.
3. Include canonical names and aliases (`sp`, `lr`, `pc`) as needed.

Validation gate:
1. `register read` in LLDB shows all Little-64 registers by name.
2. PC/SP values are coherent while stepping.

#### Step 4: Wire VS Code launch flow using LLDB DAP

1. Add `.vscode/launch.json` templates using `lldb-dap` + gdb-remote attach.
2. Add tasks for assemble/compile/link/run-debug-server lifecycle.
3. Document one-command loop in this file and project README docs.

Validation gate:
1. Breakpoint/step/register/memory workflow works entirely from VS Code.
2. Same binary can be debugged headless (CLI LLDB) and in VS Code.

### Track 2 — Full Native LLDB Target Support (Deeper investment)

Goal: first-class Little-64 architecture support inside LLDB itself.

#### Step 5: Add Little-64 architecture identity in LLDB

1. Extend LLDB architecture enums in:
   - `compilers/llvm/llvm-project/lldb/include/lldb/Utility/ArchSpec.h`
2. Map triple/core properties in:
   - `compilers/llvm/llvm-project/lldb/source/Utility/ArchSpec.cpp`
3. Ensure `llvm::Triple::little64` resolves to valid LLDB `ArchSpec`.

Validation gate:
1. LLDB internal arch parsing recognizes `little64` triples.
2. No regressions for existing architectures.

#### Step 6: Implement Little-64 register info and register context

1. Add register enum/header entries under:
   - `lldb/source/Plugins/Process/Utility/`
2. Implement `RegisterInfo*` and `RegisterContext*` classes for Little-64.
3. Map DWARF register numbers consistently with LLVM backend definitions.

Validation gate:
1. LLDB reads/writes registers through native abstractions.
2. Frame 0 register state remains consistent across continue/step/stop cycles.

#### Step 7: Add process/plugin integration points

1. Integrate Little-64 into the chosen process path:
   - gdb-remote plugin path first (recommended), then native as needed.
2. Hook architecture-specific fallbacks where required (register fallback logic).
3. Keep transport-independent register semantics in shared utility classes.

Validation gate:
1. LLDB no longer depends solely on XML fallback for core register semantics.
2. Standard LLDB flows (`thread`, `register`, `memory`) are stable.

#### Step 8: ABI + unwind + call frame semantics

1. Define Little-64 ABI plugin behavior:
   - argument/return register mapping,
   - stack/frame canonical rules,
   - function call boundary behavior.
2. Implement unwind plan support (prologue/epilogue-aware where feasible).

Validation gate:
1. Backtraces are correct for non-trivial call chains.
2. Stepping across call/return behaves correctly.

#### Step 9: Breakpoints, exceptions, and stop reason richness

1. Distinguish stop reasons (breakpoint, step, trap/fault, interrupt).
2. Add/watchpoint semantics only after core breakpoint path is stable.
3. Ensure fault metadata is preserved for OS/paging bring-up workflows.

Validation gate:
1. Stop reason classification is deterministic and user-visible in LLDB/VS Code.
2. Fault-driven debug loops are practical for BIOS/OS work.

#### Step 10: LLDB test coverage and CI entry points

1. Add targeted LLDB tests for:
   - arch detection,
   - register read/write,
   - step/continue,
   - breakpoints,
   - basic unwind.
2. Add optional CI lane for LLDB smoke tests (non-blocking initially).

Validation gate:
1. LLDB regressions are caught automatically.
2. Bring-up is reproducible for new contributors.

### Recommended Execution Order

1. Complete Track 1 Steps 1–4 first to unlock immediate VS Code value.
2. Start Track 2 only after Track 1 is stable and documented.
3. Implement Track 2 in thin vertical slices (ArchSpec → Registers → Unwind), validating each slice before expanding scope.

### Definition of Done (LLDB Bring-up)

1. `lldb` + `lldb-dap` are built and available in `compilers/bin`.
2. VS Code debugging works for Little-64 binaries via repeatable project tasks.
3. Core debugging loop is stable: breakpoints, continue, step, register/memory inspect.
4. Architecture-specific behavior is covered by automated LLDB-facing tests.

## VS Code Deliverables

1. `.vscode/tasks.json` templates
   - Build emulator/toolchain
   - Assemble/compile/link test artifacts
   - Run test binary under emulator
2. `.vscode/launch.json` templates
   - Attach/launch through gdb remote session
3. Workspace docs
   - One-command debug flow for BIOS/OS binaries
   - Known assumptions (ports, image paths, entry points)

## Track 1 Status (Implemented)

The LLDB-side Track 1 bootstrap is now in place:

1. Toolchain build support for LLDB artifacts:
   - `compilers/llvm/build.sh` supports `ENABLE_LLDB=1`.
   - This builds and exports `lldb` and `lldb-dap` to `compilers/bin`.
2. VS Code templates:
   - `.vscode/tasks.json` includes LLDB toolchain prep tasks.
   - `.vscode/launch.json` includes an LLDB DAP attach template using GDB RSP.

Quick commands:

1. Build LLDB-enabled toolchain:
   - `cd compilers && ENABLE_LLDB=1 ./build.sh llvm`
2. Verify binaries:
   - `./bin/lldb --version`
   - `./bin/lldb-dap --help`

Current limitation:

1. Current emulator target XML exposes core register set only (16 GPR + flags).
2. Continue (`c`) is run-until-stop and is typically interrupted from client with `0x03` unless a virtual breakpoint is hit.

Emulator-side implementation status:

1. `little-64-debug` now serves GDB RSP over TCP:
   - `./builddir/little-64-debug 9000`
2. Implemented baseline packets:
   - `qSupported`, `?`, `c`, `s`, interrupt `0x03`, `g`, `m`, `Z0`/`z0`
3. LLDB compatibility helpers added:
   - `qXfer:features:read:target.xml`, thread queries (`qfThreadInfo`, `qsThreadInfo`, `qC`), `H*`, `vCont?`/`vCont;c`/`vCont;s`.

End-to-end smoke workflow:

1. Build smoke ELF and debug server:
   - `meson compile -C builddir little-64-debug`
   - `compilers/bin/llvm-mc -triple=little64 -filetype=obj asm/debug_smoke.asm -o builddir/debug-smoke.o`
   - `compilers/bin/ld.lld builddir/debug-smoke.o -o builddir/debug-smoke.elf`
2. Run RSP server with ELF preload:
   - `./builddir/little-64-debug 9000 builddir/debug-smoke.elf`
3. Attach from LLDB:
   - `compilers/bin/lldb --batch -o "gdb-remote 127.0.0.1:9000" -o "process continue"`

Current LLDB limitation:

1. LLDB-native breakpoint insertion commands (`breakpoint set ...`) are not stable yet for Little-64 because native LLDB architecture support is still missing (Track 2).
2. Emulator-side virtual breakpoints via raw RSP `Z0`/`z0` are implemented and covered by integration tests.

Automated coverage:

1. `tests/debug/test_rsp_server.py` performs end-to-end RSP validation against a real preloaded ELF.
2. Run via Meson:
   - `meson test -C builddir debug-rsp-integration --print-errorlogs`
   - `meson test -C builddir debug-lldb-remote-smoke --print-errorlogs`

## Acceptance Criteria

1. From VS Code, developer can build and launch a BIOS/OS artifact.
2. Debug session supports step/continue/register/memory/breakpoints.
3. GUI is optional; same workflow works headless in terminal/CI.
4. Paging/fault state becomes inspectable as MMU work lands.

## Non-Goals

1. Embedding full code editor and project management in Qt/ImGui frontends.
2. Duplicating LSP/navigation/refactor capabilities already in VS Code.

## Dependencies in Current Codebase

- Runtime API: `emulator/frontend_api.hpp`
- Session facade: `emulator/emulator_session.hpp/.cpp`
- Debug skeleton: `emulator/debug_server.hpp/.cpp`, `emulator/debug_transport.hpp/.cpp`
- Headless runner path: `emulator/headless_runtime.hpp/.cpp`
- Shared frontend services: `frontend/debugger_execution.hpp`, `frontend/debugger_views.hpp`
