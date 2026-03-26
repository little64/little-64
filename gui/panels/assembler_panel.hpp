#pragma once

#include <cstdint>
#include <string>

struct AppState;

class AssemblerPanel {
public:
    explicit AssemblerPanel(AppState& state);
    void render();

private:
    AppState& state;
    char editor_buf[65536] = {};  // Text buffer for ImGui::InputTextMultiline
};
