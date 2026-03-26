#pragma once

#include <cstdint>

struct AppState;

class MemoryPanel {
public:
    explicit MemoryPanel(AppState& state);
    void render();

private:
    AppState& state;
    uint64_t  page_base  = 0;
    bool      follow_pc  = true;
    char      addr_input[17] = "0000000000000000";  // hex input buffer
};
