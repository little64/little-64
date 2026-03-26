#include "assembler_panel.hpp"
#include "../app.hpp"
#include "assembler.hpp"
#include "disassembler.hpp"
#include <imgui.h>
#include <algorithm>

AssemblerPanel::AssemblerPanel(AppState& state)
    : state(state) {
    // Initialize editor buffer from editor_source if available
    if (!state.editor_source.empty()) {
        size_t len = std::min(state.editor_source.size(), size_t(65535));
        std::copy(state.editor_source.begin(), state.editor_source.begin() + len, editor_buf);
        editor_buf[len] = '\0';
    }
}

void AssemblerPanel::render() {
    if (ImGui::Begin("Assembler")) {
        // Text editor
        ImGuiInputTextFlags flags = ImGuiInputTextFlags_AllowTabInput;
        ImGui::InputTextMultiline("##editor", editor_buf, sizeof(editor_buf),
                                  ImVec2(-1, -30), flags);

        // Assemble button
        if (ImGui::Button("Assemble", ImVec2(100, 0))) {
            try {
                state.assemble_error.clear();
                Assembler assembler;
                std::vector<uint16_t> output = assembler.assemble(editor_buf);

                // Load program into CPU memory
                state.cpu.loadProgram(output);
                state.pc = 0;

                // Disassemble for display
                state.disassembly = Disassembler::disassembleBuffer(
                    reinterpret_cast<const uint16_t*>(state.cpu.getMemory()),
                    output.size(),
                    0
                );
            } catch (const std::exception& e) {
                state.assemble_error = std::string("Error: ") + e.what();
            }
        }

        // Display error message if present
        if (!state.assemble_error.empty()) {
            ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(1.0f, 0.0f, 0.0f, 1.0f));
            ImGui::TextWrapped("%s", state.assemble_error.c_str());
            ImGui::PopStyleColor();
        }
    }
    ImGui::End();
}
