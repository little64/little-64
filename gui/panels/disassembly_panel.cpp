#include "disassembly_panel.hpp"
#include <imgui.h>

DisassemblyPanel::DisassemblyPanel(DisassemblyPanelContext& state)
    : state(state) {}

void DisassemblyPanel::render() {
    if (ImGui::Begin("Disassembly")) {
        const uint64_t pc = state.emulator.pc();
        if (ImGui::BeginTable("disasm_table", 3,
                              ImGuiTableFlags_Borders | ImGuiTableFlags_RowBg | ImGuiTableFlags_ScrollY)) {
            ImGui::TableSetupColumn("Address", ImGuiTableColumnFlags_WidthFixed, 80.0f);
            ImGui::TableSetupColumn("Hex", ImGuiTableColumnFlags_WidthFixed, 60.0f);
            ImGui::TableSetupColumn("Instruction", ImGuiTableColumnFlags_WidthStretch);
            ImGui::TableHeadersRow();

            for (const auto& instr : state.disassembly) {
                ImGui::TableNextRow();

                // Highlight row if PC matches this instruction's address
                if (instr.address == pc) {
                    ImGui::TableSetBgColor(ImGuiTableBgTarget_RowBg0,
                                          ImGui::GetColorU32(ImVec4(0.3f, 0.7f, 1.0f, 0.3f)));
                }

                // Address column
                ImGui::TableSetColumnIndex(0);
                ImGui::Text("0x%04X", instr.address);

                // Hex column
                ImGui::TableSetColumnIndex(1);
                ImGui::Text("0x%04X", instr.raw);

                // Instruction text column
                ImGui::TableSetColumnIndex(2);
                ImGui::Text("%s", instr.text.c_str());
            }

            ImGui::EndTable();
        }
    }
    ImGui::End();
}
