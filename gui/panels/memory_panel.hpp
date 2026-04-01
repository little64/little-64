#pragma once

#include <cstdint>

#include "panel_contexts.hpp"

class MemoryPanel {
public:
    explicit MemoryPanel(MemoryPanelContext& state);
    void render();

private:
    MemoryPanelContext& state;
    uint64_t  page_base  = 0;
    bool      follow_pc  = true;
    char      addr_input[17] = "0000000000000000";  // hex input buffer
};
