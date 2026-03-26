#include "register_panel.hpp"
#include "../app.hpp"
#include <imgui.h>
#include <iomanip>
#include <sstream>

RegisterPanel::RegisterPanel(AppState& state)
    : state(state) {}

void RegisterPanel::render() {
    if (ImGui::Begin("Registers")) {
        if (ImGui::BeginTable("regs_table", 2, ImGuiTableFlags_Borders | ImGuiTableFlags_RowBg)) {
            ImGui::TableSetupColumn("Register", ImGuiTableColumnFlags_WidthFixed, 80.0f);
            ImGui::TableSetupColumn("Value", ImGuiTableColumnFlags_WidthStretch);
            ImGui::TableHeadersRow();

            // Display R0-R15
            for (int i = 0; i < 16; ++i) {
                ImGui::TableNextRow();
                ImGui::TableSetColumnIndex(0);

                // R0 is shown in gray (it's hardwired to zero)
                if (i == 0) {
                    ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.7f, 0.7f, 0.7f, 1.0f));
                }

                ImGui::Text("R%d", i);

                if (i == 0) {
                    ImGui::PopStyleColor();
                }

                ImGui::TableSetColumnIndex(1);

                // Format as hex
                std::ostringstream oss;
                oss << "0x" << std::hex << std::setfill('0') << std::setw(16)
                    << state.cpu.registers.regs[i];
                ImGui::Text("%s", oss.str().c_str());
            }

            // Display PC
            ImGui::TableNextRow();
            ImGui::TableSetColumnIndex(0);
            ImGui::Text("PC");
            ImGui::TableSetColumnIndex(1);
            ImGui::Text("0x%08lX", state.cpu.registers.regs[15]); // PC is R15

            ImGui::EndTable();
        }
    }
    ImGui::End();
}
