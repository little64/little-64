#include "assembler_panel.hpp"
#include "../app.hpp"
#include "assembler.hpp"
#include "disassembler.hpp"
#include <imgui.h>
#include <nfd.h>
#include <algorithm>
#include <fstream>
#include <unistd.h>
#include <climits>

static TextEditor::LanguageDefinition buildLanguageDef() {
    TextEditor::LanguageDefinition lang;
    lang.mName = "Little-64 ASM";
    lang.mSingleLineComment = ";";
    lang.mCommentStart = "/*";   // assembly has no block comments; prevents empty-string bug in TextEditor
    lang.mCommentEnd   = "*/";
    lang.mCaseSensitive = false;
    lang.mPreprocChar = 0;  // '#' is an immediate sigil here, not a preprocessor char

    // Opcodes → Keyword colour — derived from Assembler::getAllMnemonics() so that
    // real instructions (from .def files) and pseudo-instructions stay in sync
    // automatically; no manual updates needed here when the instruction set changes.
    for (const auto& mnemonic : Assembler::getAllMnemonics())
        lang.mKeywords.insert(mnemonic);

    // Registers R0–R15 → KnownIdentifier colour
    for (int i = 0; i <= 15; ++i) {
        std::string reg = "R" + std::to_string(i);
        lang.mIdentifiers[reg] = TextEditor::Identifier{};
    }

    // Regex tokens (matched in order, first match wins):
    // Label definitions (identifier:) — must come before bare identifier matching
    lang.mTokenRegexStrings.push_back({ "[a-zA-Z_][a-zA-Z0-9_.]*:",         TextEditor::PaletteIndex::CharLiteral });
    // Directives — all recognised forms (.org, .byte, .short, .word, .int, .long, .ascii, .asciiz)
    // asciiz must appear before ascii so it is tried first
    lang.mTokenRegexStrings.push_back({ "\\.(?:asciiz|ascii|short|long|word|byte|int|org)", TextEditor::PaletteIndex::Preprocessor });
    // String literals for .ascii/.asciiz — handles common escape sequences
    lang.mTokenRegexStrings.push_back({ "\"(?:[^\"\\\\]|\\\\.)*\"",          TextEditor::PaletteIndex::String });
    // PC-relative operands: @label, @+N, @-N (label names may contain dots)
    lang.mTokenRegexStrings.push_back({ "@[+\\-]?[a-zA-Z0-9_.]+",           TextEditor::PaletteIndex::PreprocIdentifier });
    // Hex numbers (#0xFF / 0xFF)
    lang.mTokenRegexStrings.push_back({ "#?0[xX][0-9a-fA-F]+",              TextEditor::PaletteIndex::Number });
    // Binary numbers (#0b101 / 0b101)
    lang.mTokenRegexStrings.push_back({ "#?0[bB][01]+",                      TextEditor::PaletteIndex::Number });
    // Decimal numbers (#123 / 123)
    lang.mTokenRegexStrings.push_back({ "#?[0-9]+",                          TextEditor::PaletteIndex::Number });
    // Fallback identifier (dots included for JUMP.Z, LDI.S1, etc.)
    // Must be last — specific patterns above get priority.
    // Assigning Identifier triggers the keyword/known-identifier lookup in TextEditor.
    lang.mTokenRegexStrings.push_back({ "[a-zA-Z_][a-zA-Z0-9_.]*",           TextEditor::PaletteIndex::Identifier });

    return lang;
}

// VS Code-inspired palette — bright, high-contrast colours on a dark background
static TextEditor::Palette buildPalette() {
    auto p = TextEditor::GetDarkPalette();
    // Default text and identifiers (labels, unknown names) — near-white
    p[(int)TextEditor::PaletteIndex::Default]          = IM_COL32(0xD4, 0xD4, 0xD4, 0xFF);
    p[(int)TextEditor::PaletteIndex::Identifier]       = IM_COL32(0xD4, 0xD4, 0xD4, 0xFF);
    // Opcodes — warm yellow (VS Code function colour)
    p[(int)TextEditor::PaletteIndex::Keyword]          = IM_COL32(0xDC, 0xDC, 0xAA, 0xFF);
    // Registers — sky blue (VS Code variable colour)
    p[(int)TextEditor::PaletteIndex::KnownIdentifier]  = IM_COL32(0x9C, 0xDC, 0xFE, 0xFF);
    // Numeric literals — warm orange
    p[(int)TextEditor::PaletteIndex::Number]           = IM_COL32(0xD7, 0xBA, 0x7D, 0xFF);
    // Comments — neutral grey (de-emphasised; the default green dominated heavily commented files)
    p[(int)TextEditor::PaletteIndex::Comment]          = IM_COL32(0x7F, 0x84, 0x8E, 0xFF);
    p[(int)TextEditor::PaletteIndex::MultiLineComment] = IM_COL32(0x7F, 0x84, 0x8E, 0xFF);
    // Directives (.org, .word) — orchid purple (VS Code keyword colour)
    p[(int)TextEditor::PaletteIndex::Preprocessor]     = IM_COL32(0xC5, 0x86, 0xC0, 0xFF);
    // String literals ("hello") — warm orange (VS Code string colour)
    p[(int)TextEditor::PaletteIndex::String]           = IM_COL32(0xCE, 0x91, 0x78, 0xFF);
    // PC-relative operands (@label, @+N) — mint green (address references)
    p[(int)TextEditor::PaletteIndex::PreprocIdentifier]= IM_COL32(0x7D, 0xCE, 0xA0, 0xFF);
    // Label definitions (identifier:) — bright gold
    p[(int)TextEditor::PaletteIndex::CharLiteral]      = IM_COL32(0xFF, 0xD7, 0x00, 0xFF);
    // Line numbers — dim grey
    p[(int)TextEditor::PaletteIndex::LineNumber]       = IM_COL32(0x85, 0x85, 0x85, 0xFF);
    return p;
}

AssemblerPanel::AssemblerPanel(AppState& state)
    : state(state) {
    editor.SetLanguageDefinition(buildLanguageDef());
    editor.SetPalette(buildPalette());
    editor.SetText(state.editor_source);
    last_saved_content = state.editor_source;
}

void AssemblerPanel::render() {
    if (ImGui::Begin("Assembler")) {
        // Keyboard shortcuts
        ImGuiIO& io = ImGui::GetIO();
        if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_O)) openFile();
        if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_S)) saveFile();

        // Ctrl+scroll to resize editor font
        if (io.KeyCtrl && ImGui::IsWindowHovered(ImGuiHoveredFlags_ChildWindows)) {
            if (io.MouseWheel > 0.0f)
                state.editor_font_idx = std::min(state.editor_font_idx + 1,
                                                 (int)state.editor_fonts.size() - 1);
            else if (io.MouseWheel < 0.0f)
                state.editor_font_idx = std::max(state.editor_font_idx - 1, 0);
        }

        // Toolbar
        if (ImGui::Button("Open", ImVec2(60, 0))) openFile();
        ImGui::SameLine();
        if (ImGui::Button("Save", ImVec2(60, 0))) saveFile();
        ImGui::SameLine();
        if (ImGui::Button("Save As", ImVec2(70, 0))) saveFileAs();
        ImGui::SameLine();
        if (ImGui::Button("A-", ImVec2(28, 0)))
            state.editor_font_idx = std::max(state.editor_font_idx - 1, 0);
        ImGui::SameLine();
        if (ImGui::Button("A+", ImVec2(28, 0)))
            state.editor_font_idx = std::min(state.editor_font_idx + 1,
                                             (int)state.editor_fonts.size() - 1);
        ImGui::SameLine(ImGui::GetWindowWidth() - 250);
        ImGui::TextDisabled("File: ");
        ImGui::SameLine();

        // Display file name (or <untitled>)
        std::string display_name = state.current_file.empty() ? "<untitled>" : state.current_file;
        size_t last_slash = display_name.find_last_of("/\\");
        if (last_slash != std::string::npos)
            display_name = display_name.substr(last_slash + 1);

        // Unsaved indicator
        if (editor.GetText() != last_saved_content)
            display_name += " *";

        ImGui::TextWrapped("%s", display_name.c_str());

        ImGui::Separator();

        // Syntax-highlighting editor (leaves ~55px for the button row below)
        ImFont* editor_font = (!state.editor_fonts.empty() &&
                               state.editor_font_idx < (int)state.editor_fonts.size() &&
                               state.editor_fonts[state.editor_font_idx])
                              ? state.editor_fonts[state.editor_font_idx] : nullptr;
        if (editor_font) ImGui::PushFont(editor_font);
        editor.Render("##editor", ImVec2(-1, -55));
        if (editor_font) ImGui::PopFont();
        state.editor_source = editor.GetText();

        // Assemble button
        if (ImGui::Button("Assemble", ImVec2(100, 0))) {
            try {
                state.assemble_error.clear();
                Assembler assembler;
                std::vector<uint16_t> output = assembler.assemble(state.editor_source);

                state.cpu.loadProgram(output);
                state.disassembly = Disassembler::disassembleBuffer(
                    output.data(), output.size(), 0);

                editor.SetErrorMarkers({});
            } catch (const std::exception& e) {
                state.assemble_error = std::string("Error: ") + e.what();

                // Parse "at line N" to highlight the offending line
                TextEditor::ErrorMarkers markers;
                auto pos = state.assemble_error.rfind("at line ");
                if (pos != std::string::npos) {
                    try {
                        int line = std::stoi(state.assemble_error.substr(pos + 8));
                        markers[line] = e.what();
                    } catch (...) {}
                }
                editor.SetErrorMarkers(markers);
            }
        }

        // Error message
        if (!state.assemble_error.empty()) {
            ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(1.0f, 0.0f, 0.0f, 1.0f));
            ImGui::TextWrapped("%s", state.assemble_error.c_str());
            ImGui::PopStyleColor();
        }
    }
    ImGui::End();
}

// Returns the directory to use as the NFD default path.
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
        dir.empty() ? nullptr : dir.c_str(), nullptr);
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

    editor.SetText(contents);
    last_saved_content = contents;
    state.editor_source = contents;
    state.assemble_error.clear();
    editor.SetErrorMarkers({});
}

void AssemblerPanel::writeBufferToFile(const std::string& path) {
    std::ofstream file(path);
    if (!file.is_open()) {
        state.assemble_error = "Failed to write file: " + path;
        return;
    }

    std::string text = editor.GetText();
    file.write(text.c_str(), text.size());
    file.close();

    last_saved_content = text;
    state.editor_source = text;
    state.assemble_error.clear();
}
