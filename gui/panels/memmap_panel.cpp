#include "memmap_panel.hpp"
#include "../app.hpp"
#include <imgui.h>

MemoryMapPanel::MemoryMapPanel(AppState& state)
    : state(state) {}

void MemoryMapPanel::render() {
    if (ImGui::Begin("Memory Map")) {
        const auto& regions = state.cpu.getMemoryBus().regions();

        if (regions.empty()) {
            ImGui::TextDisabled("No memory regions loaded.");
        } else {
            ImGuiTableFlags flags = ImGuiTableFlags_Borders | ImGuiTableFlags_RowBg |
                                    ImGuiTableFlags_SizingFixedFit;
            if (ImGui::BeginTable("##memmap", 5, flags)) {
                ImGui::TableSetupColumn("Name",  ImGuiTableColumnFlags_WidthFixed, 80.0f);
                ImGui::TableSetupColumn("Base",  ImGuiTableColumnFlags_WidthFixed, 145.0f);
                ImGui::TableSetupColumn("Size",  ImGuiTableColumnFlags_WidthFixed, 100.0f);
                ImGui::TableSetupColumn("End",   ImGuiTableColumnFlags_WidthFixed, 145.0f);
                ImGui::TableSetupColumn("Type",  ImGuiTableColumnFlags_WidthFixed, 50.0f);
                ImGui::TableHeadersRow();

                for (const auto& r : regions) {
                    // Determine type and row color
                    std::string_view name = r->name();
                    const char* type_str = "MMIO";
                    ImVec4 color = ImVec4(1.0f, 0.85f, 0.2f, 1.0f);  // yellow for MMIO

                    if (name == "ROM") {
                        type_str = "ROM";
                        color = ImVec4(0.4f, 0.6f, 1.0f, 1.0f);  // blue
                    } else if (name == "RAM") {
                        type_str = "RAM";
                        color = ImVec4(0.4f, 1.0f, 0.5f, 1.0f);  // green
                    }

                    ImGui::TableNextRow();
                    ImGui::PushStyleColor(ImGuiCol_Text, color);

                    ImGui::TableNextColumn();
                    ImGui::TextUnformatted(name.data(), name.data() + name.size());

                    ImGui::TableNextColumn();
                    ImGui::Text("0x%016llX", (unsigned long long)r->base());

                    ImGui::TableNextColumn();
                    // Human-readable size
                    uint64_t sz = r->size();
                    if (sz >= 1024 * 1024)
                        ImGui::Text("%.0f MB", (double)sz / (1024.0 * 1024.0));
                    else if (sz >= 1024)
                        ImGui::Text("%.0f KB", (double)sz / 1024.0);
                    else
                        ImGui::Text("%llu B", (unsigned long long)sz);

                    ImGui::TableNextColumn();
                    ImGui::Text("0x%016llX", (unsigned long long)(r->end() - 1));

                    ImGui::TableNextColumn();
                    ImGui::TextUnformatted(type_str);

                    ImGui::PopStyleColor();
                }

                ImGui::EndTable();
            }
        }
    }
    ImGui::End();
}
