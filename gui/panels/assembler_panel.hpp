#pragma once

#include <string>
#include <vector>
#include <memory>
#include "TextEditor.h"

struct AppState;

class AssemblerPanel {
public:
    explicit AssemblerPanel(AppState& state);
    void render();

    // Open a project file (called externally, e.g. at startup).
    void openProject(const std::string& path);

private:
    // -----------------------------------------------------------------------
    // Per-tab state
    // -----------------------------------------------------------------------
    struct Tab {
        std::unique_ptr<TextEditor> editor;
        std::string path;           // absolute path, "" if new / unsaved
        std::string saved_content;  // snapshot at last disk write
        int uid;                    // stable ID for ImGui tab widget

        bool isModified() const { return editor->GetText() != saved_content; }
        std::string displayName() const;
    };

    AppState& state_;
    std::vector<std::unique_ptr<Tab>> tabs_;
    int active_tab_       = 0;
    int next_uid_         = 0;
    int request_switch_to_ = -1;  // when >= 0, force ImGui to select this tab once

    // Pending confirmations (resolved in the next render pass via modals)
    int pending_delete_tab_ = -1;

    // -----------------------------------------------------------------------
    // Tab lifecycle
    // -----------------------------------------------------------------------
    void newTab();
    void openFileInTab(const std::string& path);
    void closeTab(int idx);
    void saveTab(int idx);
    void saveTabAs(int idx);
    void saveAllTabs();

    // -----------------------------------------------------------------------
    // Project management
    // -----------------------------------------------------------------------
    void newProject();
    void openProjectDialog();
    void saveProject();
    void addFileToProject();
    void createNewFileInProject();
    void removeTabFromProject(int idx);
    void confirmDeleteTabFile(int idx);

    // -----------------------------------------------------------------------
    // Build
    // -----------------------------------------------------------------------
    void assembleActiveTab();
    void buildProject();
    void loadProgramIntoState(const std::vector<uint16_t>& program);

    // -----------------------------------------------------------------------
    // Rendering helpers
    // -----------------------------------------------------------------------
    void renderToolbar();
    void renderTabBar();
    void renderDeleteConfirmation();

    // -----------------------------------------------------------------------
    // Misc helpers
    // -----------------------------------------------------------------------
    void openFileDialog();
    std::unique_ptr<TextEditor> makeConfiguredEditor();
    std::string dialogDefaultDir() const;
    void syncCurrentFile();

    Tab& activeTab() { return *tabs_[active_tab_]; }
};
