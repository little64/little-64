#include "memory_panel.hpp"
#include <imgui.h>
#include <cctype>
#include <cstdio>
#include <cstring>

MemoryPanel::MemoryPanel(MemoryPanelContext& state)
    : state(state) {}

void MemoryPanel::render() {
    if (ImGui::Begin("Memory")) {
        // If following PC, snap page_base to the 64KB-aligned page containing PC
        uint64_t pc = state.emulator.pc();
        if (follow_pc) {
            page_base = pc & ~uint64_t{0xFFFF};
        }

        // Controls
        ImGui::Checkbox("Follow PC", &follow_pc);
        ImGui::SameLine();
        if (ImGui::Button("Prev Page")) {
            follow_pc  = false;
            page_base -= 0x10000;
        }
        ImGui::SameLine();
        if (ImGui::Button("Next Page")) {
            follow_pc  = false;
            page_base += 0x10000;
        }
        ImGui::SameLine();

        // Address jump input
        ImGui::SetNextItemWidth(150);
        if (ImGui::InputText("##addr", addr_input, sizeof(addr_input),
                             ImGuiInputTextFlags_CharsHexadecimal |
                             ImGuiInputTextFlags_EnterReturnsTrue)) {
            uint64_t jumped = 0;
            if (sscanf(addr_input, "%llx", (unsigned long long*)&jumped) == 1) {
                page_base = jumped & ~uint64_t{0xFFFF};
                follow_pc = false;
            }
        }
        ImGui::SameLine();
        ImGui::TextDisabled("(Enter hex addr)");

        // Show current page range
        ImGui::Text("Page: 0x%016llX - 0x%016llX",
                    (unsigned long long)page_base,
                    (unsigned long long)(page_base + 0xFFFF));
        ImGui::Separator();

        // Virtual scrolling: 4096 rows × 16 bytes = 64KB per page
        constexpr int ROWS = 4096;
        ImGuiListClipper clipper;
        clipper.Begin(ROWS);

        while (clipper.Step()) {
            for (int row = clipper.DisplayStart; row < clipper.DisplayEnd; ++row) {
                uint64_t row_addr = page_base + static_cast<uint64_t>(row) * 16;

                char buf[256];
                int  offset = 0;

                // Address
                offset += snprintf(buf + offset, sizeof(buf) - offset,
                                   "0x%016llX: ", (unsigned long long)row_addr);

                // Hex bytes with gap at byte 8
                uint8_t bytes[16];
                for (int i = 0; i < 16; ++i) {
                    bytes[i] = state.emulator.memoryRead8(row_addr + i);
                    if (i == 8) offset += snprintf(buf + offset, sizeof(buf) - offset, "  ");
                    offset += snprintf(buf + offset, sizeof(buf) - offset, "%02X ", bytes[i]);
                }

                offset += snprintf(buf + offset, sizeof(buf) - offset, "| ");

                // ASCII
                for (int i = 0; i < 16; ++i) {
                    buf[offset++] = std::isprint(bytes[i]) ? (char)bytes[i] : '.';
                }
                buf[offset] = '\0';

                // Highlight the row containing the PC
                bool is_pc_row = (pc >= row_addr && pc < row_addr + 16);
                if (is_pc_row)
                    ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.4f, 0.8f, 1.0f, 1.0f));

                ImGui::TextUnformatted(buf);

                if (is_pc_row)
                    ImGui::PopStyleColor();
            }
        }
    }
    ImGui::End();
}
