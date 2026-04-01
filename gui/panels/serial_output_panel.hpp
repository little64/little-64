#pragma once

#include "panel_contexts.hpp"

class SerialOutputPanel {
public:
    explicit SerialOutputPanel(SerialOutputPanelContext& state);
    void render();

private:
    SerialOutputPanelContext& state;
    bool auto_scroll = true;
};
