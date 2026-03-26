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

                std::string name;
                switch(i) {
                    case 13: name = "SP"; break;
                    case 14: name = "LR"; break;
                    case 15: name = "PC"; break;
                    default: name = "R" + std::to_string(i);
                }

                ImGui::Text("%s", name.c_str());

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

            ImGui::EndTable();
        }
    }
    ImGui::End();
}
