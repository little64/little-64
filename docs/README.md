# Little-64 Documentation Index

This index is the entry point for project docs.

## Recommended Read Order

1. `../README.md`
2. `../CPU_ARCH.md`
3. `assembly-syntax.md`
4. `architecture-boundaries.md`
5. `paging-v1.md`
6. `device-framework.md`
7. `vscode-integration.md`
8. `../GUI_DEBUGGER.md`

## Architecture & Behavior

- `../CPU_ARCH.md` — instruction formats, opcode map, register/flag behavior
- `architecture-boundaries.md` — layering and API boundaries
- `paging-v1.md` — v1 paging, boot-mode, and minimal hypercall contract
- `device-framework.md` — memory-region/device lifecycle model

## Authoring & Tooling

- `assembly-syntax.md` — LLVM assembly workflow and compatibility notes
- `vscode-integration.md` — VS Code + RSP workflow
- `qt-frontend.md` — Qt frontend scope and status

## Generated Docs

Build locally (strict mode):

```bash
python3 -m venv .venv-docs
./.venv-docs/bin/pip install -r requirements-docs.txt
./.venv-docs/bin/sphinx-build -n -W -b html docs/sphinx docs/_build/html
```

Alternative entry points:

- Meson target: `meson compile -C builddir docs`
- VS Code task: `little64: docs all`

## Active Roadmaps

- `lldb-arch-roadmap.md` — phased plan for LLDB-native Little64 architecture support

## Update Contract

For each behavior change:

- update at least one behavior doc (`CPU_ARCH.md`, `architecture-boundaries.md`, `device-framework.md`) when architecture/runtime semantics change,
- update `assembly-syntax.md` if LLVM assembly behavior or compatibility rules changed,
- update command examples in docs if CLI behavior changed,
- keep `CLAUDE.md` synchronized with practical contributor steps.

## Style Rules

1. Prefer "source-of-truth" references to duplicated facts.
2. Keep examples executable against current CLI behavior.
3. Add a short "Update Checklist" section to docs that are likely to drift.
4. Avoid status-heavy prose that can become stale quickly.
