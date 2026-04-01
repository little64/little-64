#pragma once

#include "panel_contexts.hpp"

class RegisterPanel {
public:
    explicit RegisterPanel(RegisterPanelContext& state);
    void render();

private:
    RegisterPanelContext& state;
};
