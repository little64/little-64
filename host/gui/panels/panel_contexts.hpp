#pragma once

#include <string>
#include <vector>

#include "../../emulator/emulator_session.hpp"
#include "../../emulator/frontend_api.hpp"
#include "../../disassembler/disassembler.hpp"

struct ImFont;

struct AssemblerPanelContext {
    EmulatorSession& emulator;
    std::vector<DisassembledInstruction>& disassembly;
    std::string& assemble_error;
    std::string& current_file;
    std::string& project_path;
    std::vector<ImFont*>& editor_fonts;
    int& editor_font_idx;
};

struct ControlPanelContext {
    IEmulatorRuntime& emulator;
    float& ui_scale;
    bool& ui_scale_dirty;
    bool& reset_layout_requested;
    bool& save_project_layout_requested;
    bool& load_project_layout_requested;
    const std::string& project_path;
};

struct DisassemblyPanelContext {
    EmulatorSession& emulator;
    std::vector<DisassembledInstruction>& disassembly;
};

struct RegisterPanelContext {
    EmulatorSession& emulator;
};

struct MemoryPanelContext {
    EmulatorSession& emulator;
};

struct SerialOutputPanelContext {
    std::string& serial_output;
};

struct MemoryMapPanelContext {
    EmulatorSession& emulator;
};
