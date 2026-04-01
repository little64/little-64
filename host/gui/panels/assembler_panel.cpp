#include "assembler_panel.hpp"
#include "compiler.hpp"
#include "llvm_assembler.hpp"
#include "disassembler.hpp"
#include "linker.hpp"
#include "project.hpp"
#include <imgui.h>
#include <nfd.h>
#include <algorithm>
#include <fstream>
#include <unistd.h>
#include <climits>
#include <cstring>
#include <regex>
#include <vector>

// ===========================================================================
// Language definition and palette (unchanged from previous implementation)
// ===========================================================================

static TextEditor::LanguageDefinition buildLanguageDef() {
    TextEditor::LanguageDefinition lang;
    lang.mName = "Little-64 ASM";
    lang.mSingleLineComment = ";";
    lang.mCommentStart = "/*";
    lang.mCommentEnd   = "*/";
    lang.mCaseSensitive = false;
    lang.mPreprocChar = 0;

    static const std::vector<std::string> mnemonics = {
        "LDI", "LDI.S1", "LDI.S2", "LDI.S3",
        "ADD", "SUB", "TEST", "AND", "OR", "XOR", "MUL", "DIV", "MOD", "STOP",
        "LOAD", "STORE", "PUSH", "POP", "MOVE",
        "BYTE_LOAD", "BYTE_STORE", "SHORT_LOAD", "SHORT_STORE", "WORD_LOAD", "WORD_STORE",
        "JUMP", "JUMP.Z", "JUMP.C", "JUMP.S", "JUMP.GT", "JUMP.LT",
        "CALL", "RET", "JAL", "LDI64"
    };
    for (const auto& mnemonic : mnemonics) {
        lang.mKeywords.insert(mnemonic);
    }

    for (int i = 0; i <= 15; ++i) {
        std::string reg = "R" + std::to_string(i);
        lang.mIdentifiers[reg] = TextEditor::Identifier{};
    }

    lang.mTokenRegexStrings.push_back({ "[a-zA-Z_][a-zA-Z0-9_.]*:",         TextEditor::PaletteIndex::CharLiteral });
    lang.mTokenRegexStrings.push_back({ "\\.(?:asciiz|ascii|short|long|word|byte|int|org)", TextEditor::PaletteIndex::Preprocessor });
    lang.mTokenRegexStrings.push_back({ "\"(?:[^\"\\\\]|\\\\.)*\"",          TextEditor::PaletteIndex::String });
    lang.mTokenRegexStrings.push_back({ "@[+\\-]?[a-zA-Z0-9_.]+",           TextEditor::PaletteIndex::PreprocIdentifier });
    lang.mTokenRegexStrings.push_back({ "#?0[xX][0-9a-fA-F]+",              TextEditor::PaletteIndex::Number });
    lang.mTokenRegexStrings.push_back({ "#?0[bB][01]+",                      TextEditor::PaletteIndex::Number });
    lang.mTokenRegexStrings.push_back({ "#?[0-9]+",                          TextEditor::PaletteIndex::Number });
    lang.mTokenRegexStrings.push_back({ "[a-zA-Z_][a-zA-Z0-9_.]*",           TextEditor::PaletteIndex::Identifier });

    return lang;
}

static TextEditor::Palette buildPalette() {
    auto p = TextEditor::GetDarkPalette();
    p[(int)TextEditor::PaletteIndex::Default]          = IM_COL32(0xD4, 0xD4, 0xD4, 0xFF);
    p[(int)TextEditor::PaletteIndex::Identifier]       = IM_COL32(0xD4, 0xD4, 0xD4, 0xFF);
    p[(int)TextEditor::PaletteIndex::Keyword]          = IM_COL32(0xDC, 0xDC, 0xAA, 0xFF);
    p[(int)TextEditor::PaletteIndex::KnownIdentifier]  = IM_COL32(0x9C, 0xDC, 0xFE, 0xFF);
    p[(int)TextEditor::PaletteIndex::Number]           = IM_COL32(0xD7, 0xBA, 0x7D, 0xFF);
    p[(int)TextEditor::PaletteIndex::Comment]          = IM_COL32(0x7F, 0x84, 0x8E, 0xFF);
    p[(int)TextEditor::PaletteIndex::MultiLineComment] = IM_COL32(0x7F, 0x84, 0x8E, 0xFF);
    p[(int)TextEditor::PaletteIndex::Preprocessor]     = IM_COL32(0xC5, 0x86, 0xC0, 0xFF);
    p[(int)TextEditor::PaletteIndex::String]           = IM_COL32(0xCE, 0x91, 0x78, 0xFF);
    p[(int)TextEditor::PaletteIndex::PreprocIdentifier]= IM_COL32(0x7D, 0xCE, 0xA0, 0xFF);
    p[(int)TextEditor::PaletteIndex::CharLiteral]      = IM_COL32(0xFF, 0xD7, 0x00, 0xFF);
    p[(int)TextEditor::PaletteIndex::LineNumber]       = IM_COL32(0x85, 0x85, 0x85, 0xFF);
    return p;
}

// ===========================================================================
// Tab::displayName
// ===========================================================================

std::string AssemblerPanel::Tab::displayName() const {
    if (path.empty()) return "<untitled>";
    size_t slash = path.find_last_of("/\\");
    return (slash == std::string::npos) ? path : path.substr(slash + 1);
}

// ===========================================================================
// Constructor
// ===========================================================================

AssemblerPanel::AssemblerPanel(AssemblerPanelContext& state)
    : state_(state)
{
    const std::string& last = state_.current_file;
    if (!last.empty()) {
        // Check extension
        if (last.size() >= 8 && last.substr(last.size() - 8) == ".l64proj") {
            openProject(last);
        } else {
            openFileInTab(last);
        }
    }
    if (tabs_.empty()) newTab();
}

// ===========================================================================
// Misc helpers
// ===========================================================================

std::unique_ptr<TextEditor> AssemblerPanel::makeConfiguredEditor() {
    auto ed = std::make_unique<TextEditor>();
    ed->SetLanguageDefinition(buildLanguageDef());
    ed->SetPalette(buildPalette());
    return ed;
}

static std::string fileExtension(const std::string& path) {
    auto dot = path.find_last_of('.');
    if (dot == std::string::npos) return {};
    std::string ext = path.substr(dot + 1);
    for (auto& c : ext) c = static_cast<char>(std::tolower(c));
    return ext;
}

static bool isCSource(const std::string& ext) {
    return ext == "c" || ext == "cpp" || ext == "cc";
}

std::string AssemblerPanel::dialogDefaultDir() const {
    // Use active tab's directory, then project directory, then cwd
    if (!tabs_.empty() && !tabs_[active_tab_]->path.empty()) {
        const auto& p = tabs_[active_tab_]->path;
        size_t slash = p.find_last_of("/\\");
        if (slash != std::string::npos)
            return p.substr(0, slash);
    }
    if (!state_.project_path.empty()) {
        size_t slash = state_.project_path.find_last_of("/\\");
        if (slash != std::string::npos)
            return state_.project_path.substr(0, slash);
    }
    char cwd[PATH_MAX];
    if (getcwd(cwd, sizeof(cwd))) return cwd;
    return {};
}

void AssemblerPanel::syncCurrentFile() {
    if (!state_.project_path.empty()) {
        state_.current_file = state_.project_path;
    } else if (!tabs_.empty()) {
        state_.current_file = tabs_[active_tab_]->path;
    }
}

void AssemblerPanel::loadProgramIntoState(const std::vector<uint16_t>& program,
                                           uint64_t entry_offset) {
    state_.emulator.loadProgram(program, 0, entry_offset);
    state_.disassembly = Disassembler::disassembleBuffer(program.data(), program.size(), 0);
}

// ===========================================================================
// Tab lifecycle
// ===========================================================================

void AssemblerPanel::newTab() {
    auto tab      = std::make_unique<Tab>();
    tab->editor   = makeConfiguredEditor();
    tab->path     = {};
    tab->saved_content = {};
    tab->uid      = next_uid_++;
    tabs_.push_back(std::move(tab));
    active_tab_   = static_cast<int>(tabs_.size()) - 1;
    syncCurrentFile();
}

void AssemblerPanel::openFileInTab(const std::string& path) {
    // If already open, just switch to that tab
    for (int i = 0; i < (int)tabs_.size(); ++i) {
        if (tabs_[i]->path == path) {
            active_tab_        = i;
            request_switch_to_ = i;
            syncCurrentFile();
            return;
        }
    }

    std::ifstream f(path);
    if (!f.is_open()) {
        state_.assemble_error = "Cannot open file: " + path;
        return;
    }
    std::string contents((std::istreambuf_iterator<char>(f)),
                         std::istreambuf_iterator<char>());

    auto tab           = std::make_unique<Tab>();
    tab->editor        = makeConfiguredEditor();
    tab->path          = path;
    tab->saved_content = contents;
    tab->uid           = next_uid_++;
    tab->editor->SetText(contents);
    tab->editor->SetErrorMarkers({});

    tabs_.push_back(std::move(tab));
    active_tab_        = static_cast<int>(tabs_.size()) - 1;
    request_switch_to_ = active_tab_;
    syncCurrentFile();
}

void AssemblerPanel::closeTab(int idx) {
    if (idx < 0 || idx >= (int)tabs_.size()) return;

    // Auto-save modified tabs that have a path
    if (tabs_[idx]->isModified() && !tabs_[idx]->path.empty())
        saveTab(idx);

    tabs_.erase(tabs_.begin() + idx);
    if (tabs_.empty()) newTab();

    if (active_tab_ >= (int)tabs_.size())
        active_tab_ = (int)tabs_.size() - 1;
    if (active_tab_ < 0) active_tab_ = 0;
    request_switch_to_ = active_tab_;
    syncCurrentFile();
}

void AssemblerPanel::saveTab(int idx) {
    if (idx < 0 || idx >= (int)tabs_.size()) return;
    auto& tab = *tabs_[idx];
    if (tab.path.empty()) {
        saveTabAs(idx);
        return;
    }
    std::ofstream f(tab.path);
    if (!f.is_open()) {
        state_.assemble_error = "Cannot write file: " + tab.path;
        return;
    }
    std::string text = tab.editor->GetText();
    f.write(text.c_str(), (std::streamsize)text.size());
    tab.saved_content = text;
    state_.assemble_error.clear();
}

void AssemblerPanel::saveTabAs(int idx) {
    if (idx < 0 || idx >= (int)tabs_.size()) return;
    nfdfilteritem_t filters[] = {{"Assembly Files", "asm"}};
    nfdchar_t* out = nullptr;
    std::string dir = dialogDefaultDir();
    nfdresult_t res = NFD_SaveDialog(&out, filters, 1,
                                    dir.empty() ? nullptr : dir.c_str(), nullptr);
    if (res == NFD_OKAY) {
        tabs_[idx]->path = out;
        NFD_FreePath(out);
        saveTab(idx);
        if (!state_.project_path.empty()) saveProject();
        syncCurrentFile();
    }
}

void AssemblerPanel::saveAllTabs() {
    for (int i = 0; i < (int)tabs_.size(); ++i) {
        if (tabs_[i]->isModified())
            saveTab(i);
    }
}

// ===========================================================================
// Project management
// ===========================================================================

void AssemblerPanel::openProject(const std::string& path) {
    ProjectFile proj;
    try {
        proj = ProjectFile::load(path);
    } catch (const std::exception& e) {
        state_.assemble_error = std::string("Cannot open project: ") + e.what();
        return;
    }

    // Save any modified tabs that have a path, then clear them all.
    // (Don't use closeTab() here — it calls newTab() when the list empties,
    // which would create an infinite loop.)
    for (auto& t : tabs_) {
        if (t->isModified() && !t->path.empty()) {
            std::ofstream f(t->path);
            if (f.is_open()) {
                std::string text = t->editor->GetText();
                f.write(text.c_str(), (std::streamsize)text.size());
            }
        }
    }
    tabs_.clear();
    active_tab_        = 0;
    request_switch_to_ = 0;

    state_.project_path = path;

    for (const auto& src : proj.sources)
        openFileInTab(src);

    if (tabs_.empty()) newTab();
    active_tab_        = 0;
    request_switch_to_ = 0;
    syncCurrentFile();
    state_.assemble_error.clear();
}

void AssemblerPanel::newProject() {
    nfdfilteritem_t filters[] = {{"Little-64 Project", "l64proj"}};
    nfdchar_t* out = nullptr;
    std::string dir = dialogDefaultDir();
    nfdresult_t res = NFD_SaveDialog(&out, filters, 1,
                                    dir.empty() ? nullptr : dir.c_str(), nullptr);
    if (res != NFD_OKAY) return;

    state_.project_path = out;
    NFD_FreePath(out);

    // Same pattern as openProject — clear directly to avoid the infinite loop
    for (auto& t : tabs_) {
        if (t->isModified() && !t->path.empty()) {
            std::ofstream f(t->path);
            if (f.is_open()) {
                std::string text = t->editor->GetText();
                f.write(text.c_str(), (std::streamsize)text.size());
            }
        }
    }
    tabs_.clear();
    active_tab_        = 0;
    request_switch_to_ = 0;
    newTab();

    saveProject();
    syncCurrentFile();
    state_.assemble_error.clear();
}

void AssemblerPanel::openProjectDialog() {
    nfdfilteritem_t filters[] = {{"Little-64 Project", "l64proj"}};
    nfdchar_t* out = nullptr;
    std::string dir = dialogDefaultDir();
    nfdresult_t res = NFD_OpenDialog(&out, filters, 1,
                                    dir.empty() ? nullptr : dir.c_str());
    if (res == NFD_OKAY) {
        openProject(out);
        NFD_FreePath(out);
    }
}

void AssemblerPanel::saveProject() {
    if (state_.project_path.empty()) return;

    size_t slash = state_.project_path.find_last_of("/\\");
    std::string proj_dir  = (slash != std::string::npos)
                            ? state_.project_path.substr(0, slash) : ".";
    std::string proj_name = (slash != std::string::npos)
                            ? state_.project_path.substr(slash + 1)
                            : state_.project_path;
    size_t dot = proj_name.rfind('.');
    if (dot != std::string::npos) proj_name = proj_name.substr(0, dot);

    ProjectFile proj;
    proj.path = state_.project_path;
    proj.dir  = proj_dir;
    proj.name = proj_name;
    for (const auto& t : tabs_) {
        if (!t->path.empty())
            proj.sources.push_back(t->path);
    }

    try {
        proj.save();
    } catch (const std::exception& e) {
        state_.assemble_error = std::string("Cannot save project: ") + e.what();
    }
}

void AssemblerPanel::addFileToProject() {
    nfdfilteritem_t filters[] = {{"Assembly/C/C++ Files", "asm,s,c,cpp,cc"}};
    nfdchar_t* out = nullptr;
    std::string dir = dialogDefaultDir();
    nfdresult_t res = NFD_OpenDialog(&out, filters, 1,
                                    dir.empty() ? nullptr : dir.c_str());
    if (res == NFD_OKAY) {
        openFileInTab(out);
        NFD_FreePath(out);
        saveProject();
    }
}

void AssemblerPanel::createNewFileInProject() {
    nfdfilteritem_t filters[] = {{"Assembly/C/C++ Files", "asm,c,cpp,cc"}};
    nfdchar_t* out = nullptr;
    std::string dir = dialogDefaultDir();
    nfdresult_t res = NFD_SaveDialog(&out, filters, 1,
                                    dir.empty() ? nullptr : dir.c_str(), nullptr);
    if (res != NFD_OKAY) return;

    std::string new_path = out;
    NFD_FreePath(out);

    // Create an empty file on disk
    std::ofstream f(new_path);
    if (!f.is_open()) {
        state_.assemble_error = "Cannot create file: " + new_path;
        return;
    }
    f.close();

    openFileInTab(new_path);
    saveProject();
}

void AssemblerPanel::removeTabFromProject(int idx) {
    if (idx < 0 || idx >= (int)tabs_.size()) return;
    tabs_.erase(tabs_.begin() + idx);
    if (tabs_.empty()) newTab();
    if (active_tab_ >= (int)tabs_.size()) active_tab_ = (int)tabs_.size() - 1;
    if (active_tab_ < 0) active_tab_ = 0;
    request_switch_to_ = active_tab_;
    saveProject();
    syncCurrentFile();
}

void AssemblerPanel::confirmDeleteTabFile(int idx) {
    pending_delete_tab_ = idx;
}

// ===========================================================================
// Build
// ===========================================================================

static std::optional<std::vector<uint8_t>> compileOrAssembleSource(
    const std::string& source_path,
    const std::string& source_text,
    const std::string& opt_level,
    std::string& error) {
    std::string ext = fileExtension(source_path);
    if (isCSource(ext)) {
        bool is_cpp = (ext == "cpp" || ext == "cc");
        auto compiled = Compiler::compileSourceText(source_text, source_path, is_cpp, opt_level, error);
        if (!compiled) return std::nullopt;
        return compiled;
    }

    auto assembled = LLVMAssembler::assembleSourceText(source_text, source_path, error);
    if (!assembled) return std::nullopt;
    return assembled;
}

static std::optional<int> extractErrorLine(const std::string& error) {
    auto pos = error.rfind("at line ");
    if (pos != std::string::npos) {
        try {
            return std::stoi(error.substr(pos + 8));
        } catch (...) {}
    }

    std::smatch match;
    static const std::regex llvm_style(R"(:(\d+):(\d+)?:?\s*error:)", std::regex::icase);
    if (std::regex_search(error, match, llvm_style) && match.size() >= 2) {
        try {
            return std::stoi(match[1].str());
        } catch (...) {}
    }

    return std::nullopt;
}

void AssemblerPanel::assembleActiveTab() {
    if (tabs_.empty()) return;
    state_.assemble_error.clear();
    std::string source = activeTab().editor->GetText();
    std::string path = activeTab().path;
    if (path.empty()) path = "untitled.asm";
    auto output = compileOrAssembleSource(path, source, opt_level, state_.assemble_error);
    if (!output) {
        TextEditor::ErrorMarkers markers;
        auto line = extractErrorLine(state_.assemble_error);
        if (line) {
            markers[*line] = state_.assemble_error;
        }
        activeTab().editor->SetErrorMarkers(markers);
        return;
    }
    LinkError link_err;
    auto linked = Linker::linkObjects({*output}, &link_err);
    if (!linked) {
        state_.assemble_error = "Link error: " + link_err.message;
        return;
    }
    loadProgramIntoState(*linked);
    activeTab().editor->SetErrorMarkers({});
}


void AssemblerPanel::buildProject() {
    if (tabs_.empty()) return;
    state_.assemble_error.clear();

    for (auto& t : tabs_) t->editor->SetErrorMarkers({});

    std::vector<std::vector<uint8_t>> objects;

    for (int i = 0; i < (int)tabs_.size(); ++i) {
        std::string source = tabs_[i]->editor->GetText();
        std::string source_path = tabs_[i]->path;
        if (source_path.empty())
            source_path = (isCSource(fileExtension(source_path)) ? "untitled.c" : "untitled.asm");

        auto obj = compileOrAssembleSource(source_path, source, opt_level, state_.assemble_error);
        if (!obj) {
            state_.assemble_error = tabs_[i]->displayName() + ": " + state_.assemble_error;
            TextEditor::ErrorMarkers markers;
            auto line = extractErrorLine(state_.assemble_error);
            if (line) {
                markers[*line] = state_.assemble_error;
            }
            tabs_[i]->editor->SetErrorMarkers(markers);
            active_tab_        = i;
            request_switch_to_ = i;
            return;
        }
        objects.push_back(std::move(*obj));
    }

    LinkError link_err;
    auto linked = Linker::linkObjects(objects, &link_err);
    if (!linked) {
        state_.assemble_error = "Link error: " + link_err.message;
        return;
    }
    uint64_t entry_offset = link_err.has_entry ? link_err.entry_address : 0;
    loadProgramIntoState(*linked, entry_offset);
}

// ===========================================================================
// File dialog (single-file mode)
// ===========================================================================

void AssemblerPanel::openFileDialog() {
    nfdfilteritem_t filters[] = {{"Assembly/C/C++ Files", "asm,s,c,cpp,cc"}};
    nfdchar_t* out = nullptr;
    std::string dir = dialogDefaultDir();
    nfdresult_t res = NFD_OpenDialog(&out, filters, 1,
                                    dir.empty() ? nullptr : dir.c_str());
    if (res == NFD_OKAY) {
        openFileInTab(out);
        NFD_FreePath(out);
    }
}

// ===========================================================================
// Rendering
// ===========================================================================

void AssemblerPanel::renderToolbar() {
    const bool in_project = !state_.project_path.empty();

    if (!in_project) {
        // Single-file mode
        if (ImGui::Button("New"))         newTab();
        ImGui::SameLine();
        if (ImGui::Button("Open"))        openFileDialog();
        ImGui::SameLine();
        if (ImGui::Button("Save"))        saveTab(active_tab_);
        ImGui::SameLine();
        if (ImGui::Button("Save As"))     saveTabAs(active_tab_);
        ImGui::SameLine();
        ImGui::Spacing(); ImGui::SameLine();
        if (ImGui::Button("New Project")) newProject();
        ImGui::SameLine();
        if (ImGui::Button("Open Project")) openProjectDialog();
    } else {
        // Project mode
        if (ImGui::Button("Save All"))     saveAllTabs();
        ImGui::SameLine();
        if (ImGui::Button("Close Project")) {
            state_.project_path.clear();
            syncCurrentFile();
        }
        ImGui::SameLine();
        ImGui::Spacing(); ImGui::SameLine();
        if (ImGui::Button("New File"))     createNewFileInProject();
        ImGui::SameLine();
        if (ImGui::Button("Add File"))     addFileToProject();
        ImGui::SameLine();
        if (ImGui::Button("Remove"))       removeTabFromProject(active_tab_);
        ImGui::SameLine();
        if (ImGui::Button("Delete"))       confirmDeleteTabFile(active_tab_);
    }

    // Optimization selection (always visible)
    ImGui::SameLine();
    ImGui::Text("Opt:");
    ImGui::SameLine();
    const char* opt_items[] = {"0", "1", "2", "3", "s", "z"};
    int opt_current = 0;
    for (int i = 0; i < IM_ARRAYSIZE(opt_items); ++i) {
        if (opt_level == opt_items[i]) {
            opt_current = i;
            break;
        }
    }
    if (ImGui::BeginCombo("##opt", opt_items[opt_current])) {
        for (int i = 0; i < IM_ARRAYSIZE(opt_items); ++i) {
            bool selected = (opt_current == i);
            if (ImGui::Selectable(opt_items[i], selected)) {
                opt_level = opt_items[i];
            }
            if (selected) ImGui::SetItemDefaultFocus();
        }
        ImGui::EndCombo();
    }

    // Font size buttons (always visible, right side)
    ImGui::SameLine();
    ImGui::Spacing(); ImGui::SameLine();
    if (ImGui::Button("A-"))
        state_.editor_font_idx = std::max(state_.editor_font_idx - 1, 0);
    ImGui::SameLine();
    if (ImGui::Button("A+"))
        state_.editor_font_idx = std::min(state_.editor_font_idx + 1,
                                          (int)state_.editor_fonts.size() - 1);
}

void AssemblerPanel::renderTabBar() {
    if (!ImGui::BeginTabBar("##tabs", ImGuiTabBarFlags_Reorderable)) return;

    int close_pending = -1;

    for (int i = 0; i < (int)tabs_.size(); ++i) {
        auto& tab = *tabs_[i];

        // Build display label (with dirty marker) and stable ImGui ID
        std::string label = tab.displayName();
        if (tab.isModified()) label += " *";
        label += "###tab" + std::to_string(tab.uid);

        // Only use SetSelected for one-shot programmatic switches (e.g. after
        // opening a project or creating a new file). Never set it every frame
        // for the current tab — that would fight with user clicks.
        ImGuiTabItemFlags flags = ImGuiTabItemFlags_None;
        if (i == request_switch_to_) flags |= ImGuiTabItemFlags_SetSelected;

        bool open = true;
        if (ImGui::BeginTabItem(label.c_str(), &open, flags)) {
            active_tab_ = i;
            syncCurrentFile();
            ImGui::EndTabItem();
        }
        if (!open) close_pending = i;
    }
    request_switch_to_ = -1;  // consume the one-shot request

    // "+" button adds a new file (project mode) or blank tab (single-file)
    if (ImGui::TabItemButton("+",
          ImGuiTabItemFlags_Trailing | ImGuiTabItemFlags_NoTooltip)) {
        if (!state_.project_path.empty())
            createNewFileInProject();
        else
            newTab();
    }

    ImGui::EndTabBar();

    if (close_pending >= 0) {
        if (!state_.project_path.empty())
            removeTabFromProject(close_pending);
        else
            closeTab(close_pending);
    }
}

void AssemblerPanel::renderDeleteConfirmation() {
    if (pending_delete_tab_ >= 0)
        ImGui::OpenPopup("Confirm Delete");

    if (ImGui::BeginPopupModal("Confirm Delete", nullptr,
                               ImGuiWindowFlags_AlwaysAutoResize)) {
        std::string fname = (pending_delete_tab_ >= 0 &&
                             pending_delete_tab_ < (int)tabs_.size())
                            ? tabs_[pending_delete_tab_]->displayName() : "?";
        ImGui::Text("Delete '%s' from disk?", fname.c_str());
        ImGui::Text("This cannot be undone.");
        ImGui::Spacing();

        if (ImGui::Button("Delete", ImVec2(80, 0))) {
            if (pending_delete_tab_ >= 0 &&
                pending_delete_tab_ < (int)tabs_.size()) {
                const std::string& p = tabs_[pending_delete_tab_]->path;
                if (!p.empty()) std::remove(p.c_str());
                removeTabFromProject(pending_delete_tab_);
            }
            pending_delete_tab_ = -1;
            ImGui::CloseCurrentPopup();
        }
        ImGui::SameLine();
        if (ImGui::Button("Cancel", ImVec2(80, 0))) {
            pending_delete_tab_ = -1;
            ImGui::CloseCurrentPopup();
        }
        ImGui::EndPopup();
    }
}

// ===========================================================================
// render — called once per frame
// ===========================================================================

void AssemblerPanel::render() {
    // Build window title (shows project name when open)
    std::string title;
    if (!state_.project_path.empty()) {
        size_t slash = state_.project_path.find_last_of("/\\");
        std::string proj_name = (slash != std::string::npos)
                                ? state_.project_path.substr(slash + 1)
                                : state_.project_path;
        title = "Assembler \xe2\x80\x94 " + proj_name;  // UTF-8 em dash
    } else {
        title = "Assembler";
    }
    title += "###AssemblerWindow";  // stable ImGui ID

    if (ImGui::Begin(title.c_str())) {
        ImGuiIO& io = ImGui::GetIO();

        // Keyboard shortcuts
        if (io.KeyCtrl && !io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_T))
            newTab();
        if (io.KeyCtrl && !io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_O))
            openFileDialog();
        if (io.KeyCtrl && !io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_S))
            saveTab(active_tab_);
        if (io.KeyCtrl && io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_S))
            saveTabAs(active_tab_);
        if (io.KeyCtrl && !io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_W))
            closeTab(active_tab_);
        if (io.KeyCtrl && io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_O))
            openProjectDialog();
        if (io.KeyCtrl && !io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_B)) {
            if (!state_.project_path.empty()) buildProject();
            else assembleActiveTab();
        }

        // Ctrl+scroll to resize editor font
        if (io.KeyCtrl && ImGui::IsWindowHovered(ImGuiHoveredFlags_ChildWindows)) {
            if (io.MouseWheel > 0.0f)
                state_.editor_font_idx = std::min(state_.editor_font_idx + 1,
                                                  (int)state_.editor_fonts.size() - 1);
            else if (io.MouseWheel < 0.0f)
                state_.editor_font_idx = std::max(state_.editor_font_idx - 1, 0);
        }

        renderToolbar();
        ImGui::Separator();
        renderTabBar();

        // Editor (leaves ~30px for the button row below)
        if (!tabs_.empty()) {
            ImFont* editor_font =
                (!state_.editor_fonts.empty() &&
                 state_.editor_font_idx < (int)state_.editor_fonts.size() &&
                 state_.editor_fonts[state_.editor_font_idx])
                ? state_.editor_fonts[state_.editor_font_idx] : nullptr;

            if (editor_font) ImGui::PushFont(editor_font);
            activeTab().editor->Render("##editor", ImVec2(-1, -55));
            if (editor_font) ImGui::PopFont();
        }

        // Build / Assemble button
        const bool in_project = !state_.project_path.empty();
        if (in_project) {
            if (ImGui::Button("Build Project", ImVec2(130, 0))) buildProject();
        } else {
            if (ImGui::Button("Build", ImVec2(100, 0))) assembleActiveTab();
        }

        // Error message
        if (!state_.assemble_error.empty()) {
            ImGui::Spacing();
            ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(1.0f, 0.3f, 0.3f, 1.0f));
            ImGui::TextWrapped("%s", state_.assemble_error.c_str());
            ImGui::PopStyleColor();

            if (ImGui::Button("Copy Error")) {
                ImGui::SetClipboardText(state_.assemble_error.c_str());
            }
        }
    }
    ImGui::End();

    renderDeleteConfirmation();
}
