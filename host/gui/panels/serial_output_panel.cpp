#include "serial_output_panel.hpp"
#include <imgui.h>

SerialOutputPanel::SerialOutputPanel(SerialOutputPanelContext& state)
    : state(state) {}

void SerialOutputPanel::render() {
    if (ImGui::Begin("Serial Output")) {
        if (ImGui::Button("Clear")) {
            state.serial_output.clear();
        }
        ImGui::SameLine();
        ImGui::Checkbox("Auto-scroll", &auto_scroll);

        ImGui::Separator();

        ImGui::InputTextMultiline(
            "##serial",
            const_cast<char*>(state.serial_output.c_str()),
            state.serial_output.size() + 1,
            ImVec2(-1, -1),
            ImGuiInputTextFlags_ReadOnly
        );

        if (auto_scroll && ImGui::GetScrollY() >= ImGui::GetScrollMaxY())
            ImGui::SetScrollHereY(1.0f);
    }
    ImGui::End();
}
