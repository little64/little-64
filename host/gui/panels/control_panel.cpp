#include "control_panel.hpp"
#include <imgui.h>

ControlPanel::ControlPanel(ControlPanelContext& state)
    : state(state), exec(state.emulator) {}

void ControlPanel::render() {
    if (ImGui::Begin("Control")) {
        auto status_text = exec.isRunning() ? "Running" : "Stopped";

        // If the CPU stopped itself, we disable live running
        if (!exec.isRunning() && live_running) {
            live_running = false;
        }

        ImGui::BeginDisabled(live_running);
        if (ImGui::Button("Step")) {
            if (!live_running) {
                exec.step(&error_text);
            }
        }
        ImGui::EndDisabled();

        ImGui::SameLine();

        if (ImGui::Button(live_running ? "Stop Live Run" : "Start Live Run")) {
            live_running = !live_running;
        }

        ImGui::SameLine();

        if (ImGui::Button("Reset")) {
            exec.reset();
        }

        ImGui::SameLine();

        if (ImGui::Button("Fire Interrupt (63)")) {
            exec.assertInterrupt(63);
        }

        if (ImGui::SliderInt("Running Speed (instr/frame)", &running_speed, 1, 10000)) {
            // No additional action needed
        }

        float ui_scale_percent = state.ui_scale * 100.0f;
        if (ImGui::SliderFloat("UI Scale (%)", &ui_scale_percent, 75.0f, 250.0f, "%.0f%%")) {
            state.ui_scale = ui_scale_percent / 100.0f;
            state.ui_scale_dirty = true;
        }

        if (ImGui::Button("Reset Layout")) {
            state.reset_layout_requested = true;
        }

        ImGui::SameLine();
        ImGui::BeginDisabled(state.project_path.empty());
        if (ImGui::Button("Save Project Layout")) {
            state.save_project_layout_requested = true;
        }
        ImGui::SameLine();
        if (ImGui::Button("Load Project Layout")) {
            state.load_project_layout_requested = true;
        }
        ImGui::EndDisabled();

        ImGui::Text("Status: %s", status_text);
        if (!error_text.empty()) {
            ImGui::TextColored(ImVec4(1.0f, 0.0f, 0.0f, 1.0f), "Error: %s", error_text.c_str());
        }

        if (live_running) {
            exec.runCycles(running_speed, &error_text);
            if (!error_text.empty() || !exec.isRunning()) {
                live_running = false;
            }
        }
    }
    ImGui::End();
}