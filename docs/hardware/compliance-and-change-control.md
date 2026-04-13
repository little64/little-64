# Compliance And Change Control

This chapter defines how the hardware reference stays aligned with the current implementation.

## Source-Of-Truth Hierarchy

| Rank | Source | Use |
|---|---|---|
| 1 | implementation code | authoritative behavior |
| 2 | proving tests | evidence that behavior is intentional and exercised |
| 3 | this hardware reference | human-readable contract derived from code and tests |
| 4 | workflow and tooling docs | contributor guidance and integration detail |

If the documentation conflicts with implementation, contributors MUST fix the documentation in the same change unless the implementation itself is wrong and is being corrected.

## Chapter Ownership By Change Type

| Change area | Minimum chapter updates |
|---|---|
| instruction encoding or semantics | `instruction-set.md` |
| privilege or special-register behavior | `privileged-architecture.md` |
| page-table or translation-fault behavior | `memory-translation-and-boot.md` |
| core ISA platform boundary | `platform-and-devices.md` |
| shared terminology or baseline invariants | `foundations.md` |

## Documentation Update Contract

For hardware-facing changes, documentation MUST be updated in the same change:

1. update the affected chapter under `docs/hardware/`,
2. update the implementation-specific documentation set when the change is implementation-specific,
3. update `docs/assembly-syntax.md` if assembly syntax or compatibility changed,
4. update `docs/architecture-boundaries.md` if module/API boundaries changed,
5. update `docs/device-framework.md` if device integration rules changed,
6. update `docs/tracing.md` if trace events or controls changed,
7. update `README.md` and `docs/README.md` if entry points or command examples changed,
8. update `CLAUDE.md` if contributor workflow instructions changed.

## Rules For Separating Core ISA And Implementation Detail

When a behavior is implementation-specific rather than part of the core ISA, contributors MUST document it outside the hardware reference.

Examples:

- translation-cache organization,
- boot-loader handoff details,
- implementation-specific platform memory maps,
- host-backed device behavior.

Those details MUST NOT be left undocumented. They MUST be moved into the implementation documentation set instead of being kept in the ISA chapters.

## Table, Diagram, And Example Rules

1. Use tables for register maps, bitfields, vector assignments, and opcode maps.
2. Use pseudocode or simple text diagrams for state transitions and boot flows.
3. Examples SHOULD remain executable against the current tree where practical.
4. Avoid duplicating the same fact in multiple chapters unless cross-reference pressure is unavoidable.

## Review Checklist

Before finalizing a hardware-facing change:

1. identify which chapter owns the behavior,
2. decide whether the behavior is core ISA or implementation-specific,
3. update the architecture or implementation chapter accordingly,
4. scan for stale references in `README.md`, `docs/README.md`, and Sphinx pages,
5. run at least the focused validation for the changed area,
6. rebuild the docs if paths, includes, or chapter names changed.

## Verification Commands

Typical validation commands:

```bash
meson compile -C builddir
meson test -C builddir --print-errorlogs
./.venv-docs/bin/sphinx-build -n -W -b html docs/sphinx docs/_build/html
```

Focused tests MAY be acceptable when the change is isolated, but broader tests are RECOMMENDED for cross-cutting behavior changes.

## Drift Checklist

Update this chapter when any of the following change:

1. the source-of-truth hierarchy,
2. the architecture-versus-implementation documentation boundary,
3. contributor workflow requirements,
4. documentation chapter ownership,
5. the standard validation commands.