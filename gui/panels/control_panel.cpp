#include "control_panel.hpp"
#include <imgui.h>

ControlPanel::ControlPanel(ControlPanelContext& state)
    : state(state) {}

void ControlPanel::render() {
    if (ImGui::Begin("Control")) {
        auto status_text = state.emulator.isRunning() ? "Running" : "Stopped";

        // If the CPU stopped itself, we disable live running
        if (!state.emulator.isRunning() && live_running) {
            live_running = false;
        }

        ImGui::BeginDisabled(live_running);
        if (ImGui::Button("Step")) {
            if (!live_running) {
                try {
                    state.emulator.cycle();
                } catch (const std::exception& e) {
                    error_text = e.what();
                }
            }
        }
        ImGui::EndDisabled();

        ImGui::SameLine();

        if (ImGui::Button(live_running ? "Stop Live Run" : "Start Live Run")) {
            live_running = !live_running;
        }

        ImGui::SameLine();

        if (ImGui::Button("Reset")) {
            state.emulator.reset();
        }

        ImGui::SameLine();

        if (ImGui::Button("Fire Interrupt (63)")) {
            state.emulator.assertInterrupt(63);
        }

        if (ImGui::SliderInt("Running Speed (instr/frame)", &running_speed, 1, 10000)) {
            // No additional action needed
        }

        ImGui::Text("Status: %s", status_text);
        if (!error_text.empty()) {
            ImGui::TextColored(ImVec4(1.0f, 0.0f, 0.0f, 1.0f), "Error: %s", error_text.c_str());
        }

        if (live_running) {
            try {
                for (int i = 0; i < running_speed; ++i) {
                    state.emulator.cycle();
                }
            } catch (const std::exception& e) {
                error_text = e.what();
                live_running = false;
            }
        }
    }
    ImGui::End();
}