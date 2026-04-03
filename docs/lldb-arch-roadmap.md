# LLDB Little64 Architecture Support Roadmap

This roadmap defines the path from today's RSP-compatible debugging to full LLDB-native Little64 architecture support (C breakpoints, call stack, variables, robust stepping, and DAP parity).

## Scope and Goal

Target outcome:

- Breakpoints in C source (file:line and function breakpoints) resolve and hit reliably.
- Call stack is valid across non-leaf functions.
- Locals/arguments display for normal C debug builds (`-O0 -g`).
- Step over / step into / continue / interrupt are stable in LLDB CLI and LLDB DAP.
- VS Code workflow uses standard LLDB operations instead of custom debugger workarounds.

Non-goals (for this milestone):

- Expression evaluator parity with mature Tier-1 targets.
- Full optimized-debug fidelity (`-O2/-O3`) on first pass.

## Current Baseline

- LLVM target backend for Little64 exists (`llvm/lib/Target/Little64`).
- RSP server in emulator supports baseline LLDB remote packets.
- LLDB can attach and perform basic remote register/memory operations.
- LLDB-native Little64 architecture plugin support is not implemented.

## Workstreams

### 1) LLDB Architecture Plumbing

Implement Little64-specific LLDB plugin pieces and registration:

- Add `ArchSpec` mapping and target triple handling for `little64` in LLDB plugin paths.
- Add process utility/register metadata for Little64 (register numbering, generic register mapping, aliasing rules).
- Ensure `pc`, `sp`, `lr`, and GPR mappings are canonical and consistent with RSP `target.xml`.

Definition of done:

- LLDB recognizes `little64-unknown-unknown` as a first-class arch in session setup.
- Register sets appear with correct names, sizes, and generic roles.

### 2) ABI + Call Frame Unwinding

Implement ABI and unwinding to unlock stack traces and variables:

- Add `ABILittle64` (or equivalent) for calling convention behavior in LLDB.
- Provide return address / CFA rules needed by stack walking.
- Implement unwind plan generation (prologue/epilogue analysis and/or CFI-driven path).
- Validate frame unwinding using C functions with nested calls.

Definition of done:

- `thread backtrace` is correct for a curated call-chain test binary.
- Frame selection and register recovery are stable at function boundaries.

### 3) Source-level Symbolization and Breakpoints

Make LLDB resolve and use source symbols naturally:

- Ensure debug info path works end-to-end (`clang -g` -> DWARF -> LLDB).
- Support file:line and function breakpoints through normal LLDB resolution.
- Confirm pending breakpoints resolve after target/remote attach lifecycle.

Definition of done:

- `breakpoint set --file ... --line ...` resolves without address-only fallback.
- Breakpoint list shows resolved locations and they hit at runtime.

### 4) Stepping and Run-Control Correctness

Stabilize continue/interrupt/step semantics with LLDB expectations:

- Verify stop reasons and thread stop data consistently map to LLDB state machine.
- Ensure `vCont`, `s`, `c`, interrupt paths remain deterministic.
- Add regression tests for "continue then interrupt" and "step over call".

Definition of done:

- No stuck `qC` polling loops in expected flows.
- Continue/interrupt works in LLDB CLI and LLDB DAP.

### 5) Variable Inspection

Enable practical C debug variable visibility:

- Ensure frame CFA + register locations allow LLDB to materialize locals/args.
- Validate `frame variable` on stack and register-backed locals.
- Add fixture binaries for locals, arguments, and nested scopes.

Definition of done:

- `frame variable` returns expected values on key fixtures.

### 6) VS Code / DAP Productization

Deliver production workflow once LLDB arch support is in place:

- Finalize `.vscode/launch.json` profiles for source breakpoints + call stack + variables.
- Add reproducible tasks for debug fixture build and attach.
- Keep RSP helper scripts only for server lifecycle, not symbol workarounds.

Definition of done:

- One-click BIOS debug supports source breakpoint + stack + variable workflows.

## Execution Phases

Phase A (foundation): Workstreams 1 + 2

- Stop adding workaround behavior in VS Code configs.
- Establish arch + unwinding correctness first.

Phase B (source debugging): Workstreams 3 + 5

- Turn on source breakpoints and variable inspection.

Phase C (runtime polish): Workstreams 4 + 6

- Lock run-control edge cases and DAP UX.

## Test Strategy

Project-level tests:

- Keep existing:
  - `meson test -C builddir debug-rsp-integration --print-errorlogs`
  - `meson test -C builddir debug-lldb-remote-smoke --print-errorlogs`

Add new suites:

- `tests/host/debug/test_lldb_source_breakpoints.py`
- `tests/host/debug/test_lldb_backtrace.py`
- `tests/host/debug/test_lldb_variables.py`
- `tests/host/debug/test_lldb_step_semantics.py`

Each test should run LLDB in batch mode and assert observable outputs (resolved breakpoints, frame count/order, variable values, step stop locations).

## Risks and Mitigations

- Risk: LLDB plugin surface is broad and can sprawl.
  - Mitigation: strict phase gates; no DAP UX changes before ABI/unwind is green.

- Risk: Divergence between RSP register model and LLDB register metadata.
  - Mitigation: single source-of-truth register schema; validate via automated register conformance tests.

- Risk: fragile stepping semantics.
  - Mitigation: packet-trace regression artifacts captured in CI for failures.

## Acceptance Gate (Release Checklist)

Ship "LLDB-native Little64 debug" only when all are true:

- Source breakpoints resolve and hit in BIOS C fixtures.
- Backtraces are correct for nested calls.
- Variable inspection works for core fixtures.
- Continue/interrupt/step pass deterministic regression tests.
- VS Code one-click profile works without architecture workaround assumptions.
