#pragma once

#include <string>
#include "TextEditor.h"

struct AppState;

class AssemblerPanel {
public:
    explicit AssemblerPanel(AppState& state);
    void render();

private:
    AppState& state;
    TextEditor editor;
    std::string last_saved_content;  // for unsaved-changes detection

    void openFile();
    void saveFile();
    void saveFileAs();
    void loadFileIntoBuffer(const std::string& path);
    void writeBufferToFile(const std::string& path);
};
