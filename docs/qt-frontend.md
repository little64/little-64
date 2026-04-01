# Qt Frontend (Preview)

This project now includes a parallel Qt-powered emulator/debugger frontend:

- Binary: `little-64-qt`
- UI stack: Qt Widgets
- Runtime mode: in-process (`EmulatorSession` / `IEmulatorRuntime`)
- Scope (current preview): inspect + control (registers, disassembly, memory, memory map, serial, run control)

The existing ImGui frontend (`little-64-gui`) remains available and unchanged as the primary debugger path.

## Build

Qt frontend build is controlled by Meson option `qt_frontend`:

- `auto` (default): build if Qt is detected
- `enabled`: require Qt and fail configuration if missing
- `disabled`: skip Qt frontend target

Examples:

```bash
# default behavior (auto)
meson setup builddir
meson compile -C builddir

# force enable
meson setup builddir -Dqt_frontend=enabled --reconfigure
meson compile -C builddir

# disable
meson setup builddir -Dqt_frontend=disabled --reconfigure
meson compile -C builddir
```

Run:

```bash
./builddir/little-64-qt
```

## Current Features

- Open ELF image via `File -> Open ELF...`
- Step execution, reset CPU, assert interrupt 63
- Live-run with configurable instruction budget per timer tick
- Register snapshot view (`R0..R15`, `PC`, `FLAGS`)
- Disassembly window around current PC
- Memory inspector with configurable base address
- Memory region map
- Serial output stream view
- Dockable pane layout with reset action

## Architecture Notes

- Frontend uses `EmulatorSession` from `emulator/emulator_session.hpp`
- Disassembly rendering uses `Disassembler` from `disassembler/disassembler.hpp`
- Shared run-control behavior is centralized in `frontend/debugger_execution.hpp` and reused by both `little-64-gui` and `little-64-qt`
- Shared inspector/view-model builders are centralized in `frontend/debugger_views.hpp` (register/disassembly/memory/regions/serial)
- The Qt app is intentionally isolated in `qt/` so that frontend logic can evolve independently from `gui/`

## Next Steps

1. Extract shared frontend services from ImGui panel code and use them from both frontends.
2. Add breakpoint/watchpoint substrate in runtime/debug server.
3. Add symbol-aware disassembly and richer navigation for OS development workflows.
4. Add layout/profile persistence parity with the ImGui frontend.
