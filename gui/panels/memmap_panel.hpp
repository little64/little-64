#pragma once

#include "panel_contexts.hpp"
#include <imgui.h>
#include <vector>
#include <string>

struct MemoryRegionInfo {
    uint64_t base;
    uint64_t size;
    std::string name;
    bool is_serial;
};

class MemoryMapPanel {
public:
    explicit MemoryMapPanel(MemoryMapPanelContext& state);
    void render();

private:
    MemoryMapPanelContext& state;
    std::vector<MemoryRegionInfo> regions;
    int selected_region;
    bool show_serial_details;
    void populateRegions();
    void renderRegionDetails(const MemoryRegionInfo& region);
    void renderSerialDetails();
};
