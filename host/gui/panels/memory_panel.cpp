#include "memory_panel.hpp"
#include "../../frontend/debugger_views.hpp"
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
            const uint64_t start = page_base + static_cast<uint64_t>(clipper.DisplayStart) * 16;
            const int visible_rows = clipper.DisplayEnd - clipper.DisplayStart;
            const auto rows = buildMemoryRows(state.emulator, start, visible_rows, 16, pc);

            for (const auto& row : rows) {
                std::string line;
                line.reserve(96);
                char prefix[32];
                std::snprintf(prefix, sizeof(prefix), "0x%016llX: ", (unsigned long long)row.address);
                line += prefix;

                for (int i = 0; i < 16; ++i) {
                    if (i == 8) line += " ";
                    line += row.hex_bytes.substr(static_cast<size_t>(i * 3), 3);
                }
                line += "| ";
                line += row.ascii;

                if (row.contains_pc)
                    ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.4f, 0.8f, 1.0f, 1.0f));

                ImGui::TextUnformatted(line.c_str());

                if (row.contains_pc)
                    ImGui::PopStyleColor();
            }
        }
    }
    ImGui::End();
}
