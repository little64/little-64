# Little-64 Cleanup Roadmap

Date: 2026-04-01

This roadmap tracks architecture-scale cleanup and maintainability work.

## Status Snapshot

- Build modularization: ✅ complete
- Runtime/device boundary cleanup: ✅ complete
- Test support consolidation: ✅ complete
- Documentation rewrite/normalization: ✅ complete
- MMU/paging infrastructure: ⏸️ deferred
- Deeper LLDB-native architecture support: ⏳ planned

## Current Priorities

1. Keep architecture boundaries stable while adding ISA/runtime features.
2. Maintain deterministic and scriptable debug workflows.
3. Keep docs synchronized with behavior in the same change.

## Active Workstreams

## Workstream A — Runtime and debug scale-up

- Expand debug protocol coverage as needed for OS bring-up.
- Add richer stop/fault reason reporting.
- Preserve existing RSP compatibility tests.

## Workstream B — Paging/MMU track (deferred)

- Introduce MMU translation layer.
- Add page-fault visibility and traceability.
- Ensure tooling exposes fault context cleanly.

## Workstream C — Testing and CI signal quality

- Keep suite taxonomy (`unit`, `integration`, `llvm`, `debug`, etc.) clean.
- Maintain machine-readable reports for integration flows.

## Workstream D — Documentation hygiene

- Keep docs source-of-truth centered.
- Keep update checklists present in docs likely to drift.
- Require docs update in same PR when behavior changes.

## Definition of Healthy State

The project is in healthy maintenance state when:

1. `meson compile -C builddir` succeeds,
2. `meson test -C builddir --print-errorlogs` is green,
3. docs commands/examples match current CLI behavior,
4. subsystem boundaries remain explicit and respected.

## Update Checklist

When this roadmap changes:

- update statuses and priorities here,
- update `docs/cleanup-program.md` if execution checklist changes,
- update `docs/README.md` if reading order or doc set changes.
