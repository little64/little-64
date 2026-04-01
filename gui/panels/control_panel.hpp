#pragma once

#include <cstdint>
#include <string>

#include "panel_contexts.hpp"

class ControlPanel {
public:
    explicit ControlPanel(ControlPanelContext& state);
    void render();

    bool live_running = false;
    int running_speed = 1;  // number of instructions to execute per frame when live_running is true
private:
    ControlPanelContext& state;
    std::string error_text = "";
};
