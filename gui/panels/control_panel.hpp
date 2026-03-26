#pragma once

#include <cstdint>
#include <string>

struct AppState;

class ControlPanel {
public:
    explicit ControlPanel(AppState& state);
    void render();

private:
    AppState& state;
    std::string error_text = "";
};
