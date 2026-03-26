#pragma once

struct AppState;

class RegisterPanel {
public:
    explicit RegisterPanel(AppState& state);
    void render();

private:
    AppState& state;
};
