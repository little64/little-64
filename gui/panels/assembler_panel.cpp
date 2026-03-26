#include "assembler_panel.hpp"
#include "../app.hpp"
#include "assembler.hpp"
#include "disassembler.hpp"
#include <imgui.h>
#include <nfd.h>
#include <algorithm>
#include <fstream>
#include <cstring>
#include <unistd.h>
#include <climits>

AssemblerPanel::AssemblerPanel(AppState& state)
    : state(state) {
    // Initialize editor buffer from editor_source if available
    if (!state.editor_source.empty()) {
        size_t len = std::min(state.editor_source.size(), size_t(65535));
        std::copy(state.editor_source.begin(), state.editor_source.begin() + len, editor_buf);
        editor_buf[len] = '\0';
        last_saved_content = state.editor_source;
    }
}

void AssemblerPanel::render() {
    if (ImGui::Begin("Assembler")) {
        // Keyboard shortcuts
        ImGuiIO& io = ImGui::GetIO();
        if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_O)) openFile();
        if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_S)) saveFile();

        // Toolbar
        if (ImGui::Button("Open", ImVec2(60, 0))) openFile();
        ImGui::SameLine();
        if (ImGui::Button("Save", ImVec2(60, 0))) saveFile();
        ImGui::SameLine();
        if (ImGui::Button("Save As", ImVec2(70, 0))) saveFileAs();
        ImGui::SameLine(ImGui::GetWindowWidth() - 250);
        ImGui::TextDisabled("File: ");
        ImGui::SameLine();

        // Display file name (or <untitled>)
        std::string display_name = state.current_file.empty() ? "<untitled>" : state.current_file;
        // Extract basename
        size_t last_slash = display_name.find_last_of("/\\");
        if (last_slash != std::string::npos) {
            display_name = display_name.substr(last_slash + 1);
        }

        // Add unsaved indicator if modified
        bool has_unsaved = (editor_buf != last_saved_content);
        if (has_unsaved) {
            display_name += " *";
        }

        ImGui::TextWrapped("%s", display_name.c_str());

        ImGui::Separator();

        // Text editor
        ImGuiInputTextFlags flags = ImGuiInputTextFlags_AllowTabInput;
        ImGui::InputTextMultiline("##editor", editor_buf, sizeof(editor_buf),
                                  ImVec2(-1, -55), flags);

        // Assemble button
        if (ImGui::Button("Assemble", ImVec2(100, 0))) {
            try {
                state.assemble_error.clear();
                Assembler assembler;
                std::vector<uint16_t> output = assembler.assemble(editor_buf);

                // Load program into CPU memory
                state.cpu.loadProgram(output);

                // Disassemble for display
                state.disassembly = Disassembler::disassembleBuffer(
                    output.data(),
                    output.size(),
                    0
                );
            } catch (const std::exception& e) {
                state.assemble_error = std::string("Error: ") + e.what();
            }
        }

        // Display error message if present
        if (!state.assemble_error.empty()) {
            ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(1.0f, 0.0f, 0.0f, 1.0f));
            ImGui::TextWrapped("%s", state.assemble_error.c_str());
            ImGui::PopStyleColor();
        }
    }
    ImGui::End();
}

// Returns the directory to use as the NFD default path.
// If a file is open, returns its parent directory; otherwise returns CWD.
static std::string dialogDefaultDir(const std::string& current_file) {
    if (!current_file.empty()) {
        size_t last_slash = current_file.find_last_of("/\\");
        if (last_slash != std::string::npos)
            return current_file.substr(0, last_slash);
    }
    char cwd[PATH_MAX];
    if (getcwd(cwd, sizeof(cwd)))
        return cwd;
    return {};
}

void AssemblerPanel::openFile() {
    nfdfilteritem_t filters[] = {{"Assembly Files", "asm,s"}};
    nfdchar_t* out = nullptr;
    std::string dir = dialogDefaultDir(state.current_file);
    nfdresult_t res = NFD_OpenDialog(&out, filters, 1,
        dir.empty() ? nullptr : dir.c_str());
    if (res == NFD_OKAY) {
        loadFileIntoBuffer(out);
        state.current_file = out;
        NFD_FreePath(out);
    }
}

void AssemblerPanel::saveFile() {
    if (state.current_file.empty()) {
        saveFileAs();
        return;
    }
    writeBufferToFile(state.current_file);
}

void AssemblerPanel::saveFileAs() {
    nfdfilteritem_t filters[] = {{"Assembly Files", "asm"}};
    nfdchar_t* out = nullptr;
    std::string dir = dialogDefaultDir(state.current_file);
    nfdresult_t res = NFD_SaveDialog(&out, filters, 1,
        dir.empty() ? nullptr : dir.c_str(),
        nullptr);
    if (res == NFD_OKAY) {
        state.current_file = out;
        NFD_FreePath(out);
        writeBufferToFile(state.current_file);
    }
}

void AssemblerPanel::loadFileIntoBuffer(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) {
        state.assemble_error = "Failed to open file: " + path;
        return;
    }

    std::string contents((std::istreambuf_iterator<char>(file)),
                         std::istreambuf_iterator<char>());

    // Truncate to buffer size if needed
    size_t len = std::min(contents.size(), size_t(65535));
    std::copy(contents.begin(), contents.begin() + len, editor_buf);
    editor_buf[len] = '\0';

    last_saved_content = contents;
    state.editor_source = contents;
    state.assemble_error.clear();
}

void AssemblerPanel::writeBufferToFile(const std::string& path) {
    std::ofstream file(path);
    if (!file.is_open()) {
        state.assemble_error = "Failed to write file: " + path;
        return;
    }

    file.write(editor_buf, std::strlen(editor_buf));
    file.close();

    last_saved_content = editor_buf;
    state.editor_source = editor_buf;
    state.assemble_error.clear();
}
