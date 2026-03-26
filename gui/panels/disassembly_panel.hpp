#pragma once

struct AppState;

class DisassemblyPanel {
public:
    explicit DisassemblyPanel(AppState& state);
    void render();

private:
    AppState& state;
};
