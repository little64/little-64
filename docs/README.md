# Little-64 Documentation Index

This index is the entry point for project documentation.

## Read Order (Recommended)

1. `../README.md`
2. `../CPU_ARCH.md`
3. `assembly-syntax.md`
4. `architecture-boundaries.md`
5. `device-framework.md`
6. `vscode-integration.md`
7. `../GUI_DEBUGGER.md`

## Architecture & Behavior

- `../CPU_ARCH.md` — instruction formats, opcode map, register/flag behavior
- `architecture-boundaries.md` — layering and API boundaries
- `device-framework.md` — memory-region/device lifecycle model

## Authoring & Tooling

- `assembly-syntax.md` — LLVM assembly workflow and compatibility notes
- `vscode-integration.md` — VS Code + RSP workflow
- `qt-frontend.md` — Qt frontend scope and status

## Planning Docs

- `cleanup-roadmap.md` — active roadmap and deferred items
- `cleanup-program.md` — execution checklist and acceptance criteria

## Documentation Contract

For every behavior change:

- update at least one behavior doc (`CPU_ARCH.md`, `architecture-boundaries.md`, `device-framework.md`) if architecture/runtime semantics changed,
- update `assembly-syntax.md` if LLVM assembly behavior or compatibility rules changed,
- update command examples in docs if CLI behavior changed,
- keep `CLAUDE.md` synchronized with practical contributor steps.

## Style Rules for Future Updates

1. Prefer "source-of-truth" references to duplicated facts.
2. Keep examples executable against current CLI behavior.
3. Add a short "Update Checklist" section to docs that are likely to drift.
4. Avoid status-heavy prose that can become stale quickly.
