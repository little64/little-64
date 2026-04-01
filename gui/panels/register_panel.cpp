#include "register_panel.hpp"
#include <imgui.h>
#include <iomanip>
#include <sstream>

RegisterPanel::RegisterPanel(RegisterPanelContext& state)
    : state(state) {}

void RegisterPanel::render() {
    if (ImGui::Begin("Registers")) {
        const RegisterSnapshot regs = state.emulator.registers();

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
                    << regs.gpr[i];
                ImGui::Text("%s", oss.str().c_str());
            }

            // Section header: special registers
            ImGui::TableNextRow();
            ImGui::TableSetColumnIndex(0);
            ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.8f, 0.8f, 0.4f, 1.0f));
            ImGui::Text("— Special —");
            ImGui::PopStyleColor();

            struct SREntry { const char* name; uint64_t value; const char* note; };
            SREntry sr_entries[] = {
                { "cpu_ctrl",  regs.cpu_control,          nullptr },
                { "int_table", regs.interrupt_table_base, nullptr },
                { "int_mask",  regs.interrupt_mask,       nullptr },
                { "int_state", regs.interrupt_states,     nullptr },
                { "int_epc",   regs.interrupt_epc,        nullptr },
                { "int_eflg",  regs.interrupt_eflags,     nullptr },
                { "int_excp",  regs.interrupt_except,     nullptr },
                { "int_dat0",  regs.interrupt_data[0],    nullptr },
                { "int_dat1",  regs.interrupt_data[1],    nullptr },
                { "int_dat2",  regs.interrupt_data[2],    nullptr },
                { "int_dat3",  regs.interrupt_data[3],    nullptr },
            };

            for (const auto& e : sr_entries) {
                ImGui::TableNextRow();
                ImGui::TableSetColumnIndex(0);
                ImGui::Text("%s", e.name);
                ImGui::TableSetColumnIndex(1);

                std::ostringstream oss;
                oss << "0x" << std::hex << std::setfill('0') << std::setw(16) << e.value;

                // Decode cpu_control bits inline
                if (e.name == std::string("cpu_ctrl")) {
                    bool ie    = e.value & 1;
                    bool in_i  = (e.value >> 1) & 1;
                    uint8_t cn = (e.value >> 2) & 0x3F;
                    oss << "  IE=" << ie << " IN=" << in_i << " N=" << (int)cn;
                }

                ImGui::Text("%s", oss.str().c_str());
            }

            ImGui::EndTable();
        }
    }
    ImGui::End();
}
