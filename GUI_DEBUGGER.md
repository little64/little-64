# Little-64 GUI Frontends

Little-64 provides two runtime debugger frontends:

- `little-64-gui` (ImGui)
- `little-64-qt` (Qt)

Both are debugger/inspection UIs and rely on shared runtime services.

## Build

```bash
meson compile -C builddir
```

Run:

```bash
./builddir/little-64-gui
# or
./builddir/little-64-qt
```

## ImGui Frontend Features

Current `little-64-gui` capabilities include:

- assembler editing/assembly workflow,
- disassembly around current PC,
- register and memory inspectors,
- serial output panel,
- memory-map inspection,
- execution controls.

## Shared Frontend Architecture

- Runtime contract: `host/emulator/frontend_api.hpp`
- Session facade: `host/emulator/emulator_session.hpp/.cpp`
- Shared helpers: `host/frontend/`
- ImGui-specific code: `host/gui/`
- Qt-specific code: `host/qt/`

## Recommended Usage

- Use VS Code/CLI for source editing, build orchestration, and project navigation.
- Use GUI frontends for machine-state visibility and interactive inspection.

## Troubleshooting

If GUI build fails:

1. reconfigure and rebuild:
   ```bash
   meson setup --reconfigure builddir
   meson compile -C builddir
   ```
2. inspect Meson logs in `builddir/meson-logs/`.

## Update Checklist

When frontend behavior changes:

- update this file,
- update `docs/qt-frontend.md` if Qt behavior changed,
- update `docs/architecture-boundaries.md` if layering changed.
