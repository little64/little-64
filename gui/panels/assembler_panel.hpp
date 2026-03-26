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
    std::string last_saved_content;  // for unsaved-changes detection

    void openFile();
    void saveFile();
    void saveFileAs();
    void loadFileIntoBuffer(const std::string& path);
    void writeBufferToFile(const std::string& path);
};
