# Little-64 Cleanup Program

Date: 2026-04-01

This checklist turns cleanup goals into concrete execution items.

## Workstream 1 — Build modularization

### Goal

Keep build behavior stable while making ownership local to each subsystem.

### Delivered

- top-level Meson orchestrator plus per-subsystem `meson.build` files.
- compatibility build outputs preserved at root builddir paths.

### Validation

- `meson compile -C builddir`
- `meson test -C builddir --print-errorlogs`

## Workstream 2 — Test support separation

### Goal

Separate generic test harness macros from CPU-specific helpers.

### Delivered

- canonical CPU helper header: `tests/support/cpu_test_helpers.hpp`
- compatibility shim retained: `tests/test_harness.hpp`

### Validation

- all CPU test binaries compile and pass.

## Workstream 3 — Documentation normalization

### Goal

Replace drift-prone docs with source-of-truth-centered docs and update checklists.

### Delivered

- full rewrite of project-authored documentation set,
- consistent structure across architecture/syntax/workflow docs,
- explicit maintenance contract in `CLAUDE.md` and docs index.

### Validation

- command examples match current CLI behavior,
- docs cross-references remain valid,
- full test suite remains green.

## Guardrails

1. Preserve `compilers/llvm/` and `compilers/lily-cc/` separation.
2. Prefer behavior-preserving refactors before semantic changes.
3. Keep docs updates in the same change as behavior updates.

## Ongoing Enforcement

For every architecture/tooling change:

- update the relevant docs,
- run full tests,
- keep this checklist aligned with project practice.
