#pragma once

#include <cstdint>

struct AppState;

class MemoryPanel {
public:
    explicit MemoryPanel(AppState& state);
    void render();

private:
    AppState& state;
    uint16_t scroll_offset = 0;
};
