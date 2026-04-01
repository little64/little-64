# Qt Frontend

Qt frontend target: `little-64-qt`

The Qt frontend is a debugger/inspection UI, not an IDE replacement.

## Build Control

Meson option: `qt_frontend`

- `auto` (default): build when Qt is found
- `enabled`: require Qt and fail if missing
- `disabled`: skip Qt target

Examples:

```bash
meson setup builddir -Dqt_frontend=auto
meson compile -C builddir

meson setup --reconfigure builddir -Dqt_frontend=enabled
meson setup --reconfigure builddir -Dqt_frontend=disabled
```

Run:

```bash
./builddir/little-64-qt
```

## Scope

Current scope is runtime inspection and execution control:

- load image,
- run/step/reset controls,
- register view,
- disassembly view,
- memory and region inspection,
- serial output view.

## Architecture Notes

- Runtime access via `EmulatorSession`/`IEmulatorRuntime`
- Shared frontend logic lives under `frontend/`
- Qt-specific composition and widgets remain under `qt/`

## Non-goals

- Embedding full source editing/LSP/build orchestration into frontend.
- Replacing VS Code or CLI workflows.

## Update Checklist

When Qt frontend behavior changes:

- update feature list in this document,
- update any task/launch examples in `docs/vscode-integration.md` if startup flow changes,
- verify `qt_frontend=enabled` and `qt_frontend=disabled` paths both configure correctly.
