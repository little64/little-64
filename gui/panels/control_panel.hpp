#pragma once

#include <cstdint>
#include <string>

struct AppState;

class ControlPanel {
public:
    explicit ControlPanel(AppState& state);
    void render();

    bool live_running = false;
    int running_speed = 1;  // number of instructions to execute per frame when live_running is true
private:
    AppState& state;
    std::string error_text = "";
};
