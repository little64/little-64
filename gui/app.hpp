#pragma once

#include <string>
#include <vector>
#include <memory>
#include <cstdint>

struct SDL_Window;
typedef void* SDL_GLContext;

#include "../emulator/cpu.hpp"
#include "../disassembler/disassembler.hpp"

// Shared application state passed to all panels
struct AppState {
    Little64CPU cpu;
    std::vector<DisassembledInstruction> disassembly;
    std::string editor_source;
    std::string assemble_error;
    std::string current_file;  // absolute path, or "" if untitled
};

// Forward declarations of panels
class AssemblerPanel;
class ControlPanel;
class DisassemblyPanel;
class RegisterPanel;
class MemoryPanel;

class App {
public:
    App();
    ~App();

    bool init();        // SDL2 + OpenGL + ImGui setup; returns false on failure
    void run();         // main event loop
    void shutdown();    // cleanup

private:
    void loadLastFile();   // read ~/.config/little-64/last_file into state
    void saveLastFile();   // write state.current_file to config
    AppState state;
    std::unique_ptr<AssemblerPanel>   assembler_panel;
    std::unique_ptr<ControlPanel>     control_panel;
    std::unique_ptr<DisassemblyPanel> disassembly_panel;
    std::unique_ptr<RegisterPanel>    register_panel;
    std::unique_ptr<MemoryPanel>      memory_panel;

    SDL_Window*   window  = nullptr;
    SDL_GLContext gl_ctx  = nullptr;
    bool          running = false;
};
