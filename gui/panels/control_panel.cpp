#include "control_panel.hpp"
#include "../app.hpp"
#include <imgui.h>

ControlPanel::ControlPanel(AppState& state)
    : state(state) {}

void ControlPanel::render() {
    if (ImGui::Begin("Control")) {
        if (ImGui::Button("Step")) {
            // No-op for now; will execute next instruction when implemented
        }
    }
    ImGui::End();
}