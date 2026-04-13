#include "register_panel.hpp"
#include "../../frontend/debugger_views.hpp"
#include <imgui.h>
#include <iomanip>
#include <sstream>

RegisterPanel::RegisterPanel(RegisterPanelContext& state)
    : state(state) {}

void RegisterPanel::render() {
    if (ImGui::Begin("Registers")) {
        const RegisterSnapshot regs = state.emulator.registers();
        const auto rows = buildRegisterRows(regs, state.emulator.pc());

        if (ImGui::BeginTable("regs_table", 2, ImGuiTableFlags_Borders | ImGuiTableFlags_RowBg)) {
            ImGui::TableSetupColumn("Register", ImGuiTableColumnFlags_WidthFixed, 80.0f);
            ImGui::TableSetupColumn("Value", ImGuiTableColumnFlags_WidthStretch);
            ImGui::TableHeadersRow();

            for (size_t i = 0; i < kFirstSystemRegisterRowIndex; ++i) {
                ImGui::TableNextRow();
                ImGui::TableSetColumnIndex(0);

                if (rows[i].muted) {
                    ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.7f, 0.7f, 0.7f, 1.0f));
                }

                ImGui::Text("%s", rows[i].name.c_str());

                if (rows[i].muted) {
                    ImGui::PopStyleColor();
                }

                ImGui::TableSetColumnIndex(1);

                // Format as hex
                std::ostringstream oss;
                oss << "0x" << std::hex << std::setfill('0') << std::setw(16)
                    << rows[i].value;
                ImGui::Text("%s", oss.str().c_str());
            }

            for (size_t i = kFirstSystemRegisterRowIndex; i < kFirstSpecialRegisterRowIndex; ++i) {
                ImGui::TableNextRow();
                ImGui::TableSetColumnIndex(0);
                ImGui::Text("%s", rows[i].name.c_str());
                ImGui::TableSetColumnIndex(1);

                std::ostringstream oss;
                oss << "0x" << std::hex << std::setfill('0') << std::setw(16)
                    << rows[i].value;
                ImGui::Text("%s", oss.str().c_str());
            }

            // Section header: special registers
            ImGui::TableNextRow();
            ImGui::TableSetColumnIndex(0);
            ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.8f, 0.8f, 0.4f, 1.0f));
            ImGui::Text("— Special —");
            ImGui::PopStyleColor();

            for (size_t i = 18; i < rows.size(); ++i) {
                const auto& e = rows[i];
                ImGui::TableNextRow();
                ImGui::TableSetColumnIndex(0);
                ImGui::Text("%s", e.name.c_str());
                ImGui::TableSetColumnIndex(1);

                std::ostringstream oss;
                oss << "0x" << std::hex << std::setfill('0') << std::setw(16) << e.value;

                // Decode cpu_control bits inline
                if (i == kCpuControlRowIndex) {
                    bool ie    = e.value & 1;
                    bool in_i  = (e.value >> 1) & 1;
                    uint8_t cn = (e.value >> 2) & 0x7F;
                    oss << "  IE=" << ie << " IN=" << in_i << " N=" << (int)cn;
                }

                ImGui::Text("%s", oss.str().c_str());
            }

            ImGui::EndTable();
        }
    }
    ImGui::End();
}
