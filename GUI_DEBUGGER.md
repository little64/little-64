# Little-64 GUI Debugger/Emulator

A modular ImGui-based integrated development environment for the Little-64 CPU architecture.

## Features

- **Assembler Panel**: Write and assemble Little-64 assembly code with inline error reporting
- **Disassembly View**: Display decoded instructions with the program counter highlighted
- **Register Viewer**: Monitor all 16 GPRs (R0–R15) in real-time, plus PC
- **Memory Inspector**: 64KB hex + ASCII viewer with virtual scrolling for performance

## Building

### Prerequisites

- Linux with SDL2 development headers: `sudo zypper install libSDL2-devel` (or equivalent)
- OpenGL development headers (usually included with graphics drivers)
- Meson and Ninja build tools
- GCC/Clang C++17 compiler

### Build Steps

```bash
cd /path/to/little-64

# Configure (fetches ImGui from Meson WrapDB on first run)
meson setup builddir

# Build
ninja -C builddir

# Run the GUI
./builddir/little-64-gui
```

## Usage

1. **Write assembly** in the **Assembler Panel** text editor
   - Use standard Little-64 syntax: mnemonics, registers (R0–R15), immediates, labels, directives
   - Click "Assemble" to parse and compile to binary
   - Errors appear in red below the button

2. **View disassembly** in the **Disassembly View**
   - Shows address, hex encoding, and decoded instruction text
   - PC (program counter) row is highlighted in light blue
   - "Step" button is a placeholder for future execution

3. **Monitor registers** in the **Register Viewer**
   - All 16 GPRs displayed in hex
   - R0 shown in gray (architecturally always zero)
   - PC displayed separately

4. **Inspect memory** in the **Memory Inspector**
   - 16 bytes per row, with hex and ASCII columns
   - Byte gap at offset 8 for readability
   - Non-printable ASCII shown as `.`
   - Virtual scrolling (only renders visible rows for 64KB efficiency)

## Example Workflow

```asm
; Write this in the Assembler panel:
.org 0x0000

; Load immediate into R1
LOAD #2, R1

; Load with shift
LOAD.S1 #1, R2

; Store to memory
STORE #10, R5

; Data section
.org 0x000E
.word 0xDEAD
.word 0xBEEF
```

Then click "Assemble". The disassembly view will display all instructions with their encodings, and the memory panel will show the raw bytes.

## Architecture

### Modularity

Each panel is a standalone class with a simple interface:
- Panels receive a reference to shared `AppState` (dependency injection)
- No global state or inter-panel dependencies
- Easy to add new panels or replace existing ones

### Key Classes

- **`App`**: SDL2+OpenGL3 initialization, main event loop, panel lifecycle
- **`AppState`**: Single source of truth for CPU state, disassembly cache, editor state
- **`AssemblerPanel`**: Text editor + assembly compilation
- **`DisassemblyPanel`**: Instruction listing with PC highlight
- **`RegisterPanel`**: GPR + PC display
- **`MemoryPanel`**: 64KB virtual memory viewer

### Integration with CLI Tools

The GUI reuses the existing command-line tools as static libraries:
- `little-64-asm-lib`: Assembler logic
- `little-64-disasm-lib`: Disassembler logic
- `little-64-cpu`: CPU emulator (with memory model)

## Limitations

- **CPU execution is a stub**: `dispatchInstruction()` does not actually execute instructions
- **Memory model is temporary**: 64KB flat array; will be replaced with a proper MMU later
- **No docking yet**: ImGui windows are independent; can be resized and moved but not docked together
- **Keyboard shortcuts**: Only Escape to quit

## Future Enhancements

1. Implement `dispatchInstruction()` to actually execute instructions
2. Add breakpoints and step-through debugging
3. Add a memory editor (write to memory from GUI)
4. Watchpoints and conditional breakpoints
5. ImGui docking support for window management
6. Export/import binary and assembly files
7. Syntax highlighting in assembler editor
8. Profiling and execution timeline

## Building in Release Mode

```bash
meson setup builddir -Dbuildtype=release
ninja -C builddir
```

## Troubleshooting

### GUI window doesn't appear

The application runs correctly but may not display on headless or forwarded X11 displays. Try:
- Running on a local display: `DISPLAY=:0 ./builddir/little-64-gui`
- Checking for X11 forwarding issues
- Running on a display manager with hardware acceleration

### Memory viewer is slow

The memory panel uses virtual scrolling (ImGuiListClipper) to only render visible rows. If it's still slow, check:
- That the memory panel is actually virtualized (should handle 64KB without lag)
- Your GPU drivers and OpenGL support

### Build fails

- Ensure `libSDL2-devel` is installed
- Run `meson setup builddir --reconfigure` to refresh the build
- Check `builddir/meson-logs/meson-log.txt` for detailed errors

## Contributing

The codebase is designed for easy modification:

1. Add a new panel:
   - Create `gui/panels/my_panel.hpp` and `.cpp`
   - Inherit from the implicit panel interface (just implement `render()`)
   - Receive `AppState& state` in constructor
   - Instantiate in `App::init()` using `std::make_unique`

2. Modify existing panels without affecting others

3. Add new AppState fields as needed (no hardcoded limits)

## License

Same as the Little-64 project.
