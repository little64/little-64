#pragma once

#include "panel_contexts.hpp"

class DisassemblyPanel {
public:
    explicit DisassemblyPanel(DisassemblyPanelContext& state);
    void render();

private:
    DisassemblyPanelContext& state;
};
