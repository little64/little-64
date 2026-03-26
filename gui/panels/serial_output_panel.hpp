#pragma once

struct AppState;

class SerialOutputPanel {
public:
    explicit SerialOutputPanel(AppState& state);
    void render();

private:
    AppState& state;
    bool auto_scroll = true;
};
