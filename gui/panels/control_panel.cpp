#include "control_panel.hpp"
#include "../app.hpp"
#include <imgui.h>

ControlPanel::ControlPanel(AppState& state)
    : state(state) {}

void ControlPanel::render() {
    if (ImGui::Begin("Control")) {
        auto status_text = state.cpu.isRunning ? "Running" : "Stopped";

        if (ImGui::Button("Step")) {
            try {
                state.cpu.cycle();
            } catch (const std::exception& e) {
                error_text = e.what();
            }
        }

        ImGui::Text("Status: %s", status_text);
        if (!error_text.empty()) {
            ImGui::TextColored(ImVec4(1.0f, 0.0f, 0.0f, 1.0f), "Error: %s", error_text.c_str());
        }
    }
    ImGui::End();
}