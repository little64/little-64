#include "memory_panel.hpp"
#include "../app.hpp"
#include <imgui.h>
#include <cctype>
#include <cstdio>

MemoryPanel::MemoryPanel(AppState& state)
    : state(state) {}

void MemoryPanel::render() {
    if (ImGui::Begin("Memory")) {
        ImGui::Text("Memory Viewer (64KB)");
        ImGui::Separator();

        const uint8_t* mem = state.cpu.getMemory();
        size_t mem_size = state.cpu.getMemorySize();

        // Use ListClipper for virtual scrolling (only render visible rows)
        ImGuiListClipper clipper;
        clipper.Begin(mem_size / 16);  // 4096 rows of 16 bytes each

        while (clipper.Step()) {
            for (int row = clipper.DisplayStart; row < clipper.DisplayEnd; ++row) {
                uint16_t addr = row * 16;

                // Pre-format the entire row to avoid multiple ImGui::Text calls
                char buf[256];
                int offset = 0;

                // Address
                offset += snprintf(buf + offset, sizeof(buf) - offset, "0x%04X: ", addr);

                // Hex bytes with gap at byte 8
                for (int i = 0; i < 16; ++i) {
                    if (i == 8) offset += snprintf(buf + offset, sizeof(buf) - offset, "  ");
                    offset += snprintf(buf + offset, sizeof(buf) - offset, "%02X ",
                                      (unsigned)mem[addr + i]);
                }

                offset += snprintf(buf + offset, sizeof(buf) - offset, "| ");

                // ASCII representation
                for (int i = 0; i < 16; ++i) {
                    uint8_t c = mem[addr + i];
                    buf[offset++] = std::isprint(c) ? (char)c : '.';
                }
                buf[offset] = '\0';

                ImGui::TextUnformatted(buf);
            }
        }
    }
    ImGui::End();
}
