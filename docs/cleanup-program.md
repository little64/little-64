# Little-64 Cleanup Program (Execution Checklist)

Date: 2026-04-01

This document translates cleanup goals into concrete, verifiable workstreams.

## Workstream A — Build modularity

### Goal

Keep build behavior unchanged while making build ownership local to each subsystem.

### Done

- Split top-level `meson.build` into subsystem `meson.build` files.
- Preserved existing target names and test suite tags.

### Acceptance checks

- `meson compile -C builddir` succeeds.
- `meson test -C builddir` discovers and runs the same suites as before.

## Workstream B — Test support boundaries

### Goal

Separate generic test assertions from CPU-specific test helpers.

### Done

- Introduced `tests/support/cpu_test_helpers.hpp`.
- Updated CPU tests to include the new canonical helper path.
- Retained `tests/test_harness.hpp` as compatibility shim.

### Acceptance checks

- All CPU test binaries compile and execute.
- No duplicated helper logic remains outside support headers.

## Workstream C — Contributor navigation

### Goal

Reduce onboarding friction and make ownership/discovery obvious.

### Done

- Added root `README.md` with quick-start, module map, and build-layout map.
- Added `docs/README.md` as active docs index.

### Acceptance checks

- New contributor can find build/test/debug entrypoints in under 5 minutes.
- A maintainer can locate build logic for any subsystem directly by directory.

## Guardrails

- Keep `compilers/` separation intact:
  - `compilers/llvm/`
  - `compilers/lily-cc/`
- Avoid mixing third-party/toolchain reorganization with core project cleanup.
- Prefer behavior-preserving refactors before feature-level changes.

## Next cleanup candidates (post-baseline)

1. Add CI job split by suite (`unit`, `integration`, `llvm`, `debug`).
2. Add include-boundary check script for runtime/frontends layering.
3. Break very large docs into “reference” and “how-to” pages.
4. Add per-subsystem ownership metadata (CODEOWNERS or docs equivalent).
