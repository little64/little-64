#pragma once

struct AppState;

class MemoryMapPanel {
public:
    explicit MemoryMapPanel(AppState& state);
    void render();

private:
    AppState& state;
};
