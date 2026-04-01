#include "app.hpp"
#include "panels/assembler_panel.hpp"
#include "panels/control_panel.hpp"
#include "panels/disassembly_panel.hpp"
#include "panels/register_panel.hpp"
#include "panels/memory_panel.hpp"
#include "panels/serial_output_panel.hpp"
#include "panels/memmap_panel.hpp"
#include "../frontend/debugger_views.hpp"

#include <SDL2/SDL.h>
#include <GL/gl.h>
#include <imgui.h>
#include <imgui_impl_sdl2.h>
#include <imgui_impl_opengl3.h>
#include <nfd.h>
#include <iostream>
#include <fstream>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <array>
#include <cstdlib>
#include <algorithm>

namespace {

constexpr std::array<float, 7> kEditorFontSizes = {10.0f, 12.0f, 14.0f, 16.0f, 18.0f, 20.0f, 24.0f};

const char* findSystemMonoFont() {
    static const std::array<const char*, 8> candidates = {
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/DejaVuSansMono.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationMono-Regular.ttf",
        "/usr/share/fonts/liberation-mono/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
        "/usr/share/fonts/TTF/JetBrainsMono-Regular.ttf",
        "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf",
    };

    for (const char* path : candidates) {
        if (std::filesystem::exists(path)) {
            return path;
        }
    }
    return nullptr;
}

}

App::App()
    : assembler_ctx{state.emulator, state.disassembly, state.assemble_error,
                    state.current_file, state.project_path,
                    state.editor_fonts, state.editor_font_idx}
    , control_ctx{state.emulator, state.ui_scale, state.ui_scale_dirty,
                  state.reset_layout_requested,
                  state.save_project_layout_requested,
                  state.load_project_layout_requested,
                  state.project_path}
    , disassembly_ctx{state.emulator, state.disassembly}
    , register_ctx{state.emulator}
    , memory_ctx{state.emulator}
    , serial_output_ctx{state.serial_output}
    , memmap_ctx{state.emulator} {}

App::~App() {
    shutdown();
}

bool App::init() {
    ensureConfigDir();

    // Initialize NFD
    NFD_Init();

    // Initialize SDL2
    if (SDL_Init(SDL_INIT_VIDEO) < 0) {
        std::cerr << "Failed to initialize SDL2: " << SDL_GetError() << std::endl;
        NFD_Quit();
        return false;
    }

    // Create window
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 3);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_CORE);
    SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1);

    window = SDL_CreateWindow(
        "Little-64 Debugger",
        SDL_WINDOWPOS_CENTERED,
        SDL_WINDOWPOS_CENTERED,
        1400, 900,
        SDL_WINDOW_OPENGL | SDL_WINDOW_RESIZABLE | SDL_WINDOW_SHOWN | SDL_WINDOW_ALLOW_HIGHDPI
    );
    if (!window) {
        std::cerr << "Failed to create SDL window: " << SDL_GetError() << std::endl;
        SDL_Quit();
        return false;
    }

    // Create OpenGL context
    gl_ctx = SDL_GL_CreateContext(window);
    if (!gl_ctx) {
        std::cerr << "Failed to create OpenGL context: " << SDL_GetError() << std::endl;
        SDL_DestroyWindow(window);
        SDL_Quit();
        return false;
    }

    SDL_GL_MakeCurrent(window, gl_ctx);
    SDL_GL_SetSwapInterval(1);  // Enable vsync

    // Setup Dear ImGui context
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    static std::string s_ini_path = imguiIniPath();
    io.IniFilename = s_ini_path.c_str();
    force_default_layout_once = !std::filesystem::exists(s_ini_path);

    applyUIScale();
    rebuildFonts();

    // Setup ImGui SDL2 backend
    ImGui_ImplSDL2_InitForOpenGL(window, gl_ctx);

    // Setup ImGui OpenGL3 backend
    const char* glsl_version = "#version 330 core";
    ImGui_ImplOpenGL3_Init(glsl_version);

    // Load last edited file into state before constructing panels
    loadLastFile();

    // Initialize panels
    assembler_panel     = std::make_unique<AssemblerPanel>(assembler_ctx);
    control_panel       = std::make_unique<ControlPanel>(control_ctx);
    disassembly_panel   = std::make_unique<DisassemblyPanel>(disassembly_ctx);
    register_panel      = std::make_unique<RegisterPanel>(register_ctx);
    memory_panel        = std::make_unique<MemoryPanel>(memory_ctx);
    serial_output_panel = std::make_unique<SerialOutputPanel>(serial_output_ctx);
    memmap_panel        = std::make_unique<MemoryMapPanel>(memmap_ctx);

    running = true;
    return true;
}

void App::run() {
    ImGuiIO& io = ImGui::GetIO();

    while (running) {
        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            ImGui_ImplSDL2_ProcessEvent(&event);
            switch (event.type) {
                case SDL_QUIT:
                    running = false;
                    break;
                case SDL_KEYDOWN:
                    if (event.key.keysym.sym == SDLK_ESCAPE) {
                        running = false;
                    }
                    break;
                case SDL_DISPLAYEVENT:
                case SDL_WINDOWEVENT:
                    state.ui_scale_dirty = true;
                    break;
                default:
                    break;
            }
        }

        try {
            if (state.ui_scale_dirty) {
                applyUIScale();
                rebuildFonts();
                state.ui_scale_dirty = false;
            }

            // Start ImGui frame
            ImGui_ImplOpenGL3_NewFrame();
            ImGui_ImplSDL2_NewFrame();
            ImGui::NewFrame();

            int win_w = 0, win_h = 0;
            int fb_w = 0, fb_h = 0;
            SDL_GetWindowSize(window, &win_w, &win_h);
            SDL_GL_GetDrawableSize(window, &fb_w, &fb_h);
            if (win_w > 0 && win_h > 0) {
                io.DisplayFramebufferScale = ImVec2(
                    static_cast<float>(fb_w) / static_cast<float>(win_w),
                    static_cast<float>(fb_h) / static_cast<float>(win_h));
            }

            if (state.reset_layout_requested) {
                force_default_layout_once = true;
                state.reset_layout_requested = false;
            }

            if (state.save_project_layout_requested) {
                const std::string path = projectLayoutPath();
                if (!path.empty()) {
                    std::filesystem::create_directories(std::filesystem::path(path).parent_path());
                    ImGui::SaveIniSettingsToDisk(path.c_str());
                }
                state.save_project_layout_requested = false;
            }

            if (state.load_project_layout_requested) {
                const std::string path = projectLayoutPath();
                if (!path.empty() && std::filesystem::exists(path)) {
                    ImGui::LoadIniSettingsFromDisk(path.c_str());
                    force_default_layout_once = false;
                }
                state.load_project_layout_requested = false;
            }

            updateSerialOutput();

            const ImGuiCond layout_cond = force_default_layout_once ? ImGuiCond_Always : ImGuiCond_FirstUseEver;
            force_default_layout_once = false;

            float W = io.DisplaySize.x;
            float H = io.DisplaySize.y;
            const float ctrl_h  = 90.0f * state.ui_scale;
            float left_w  = std::round(W * 0.55f);
            float right_w = W - left_w;
            float main_h  = H - ctrl_h;
            float asm_h     = std::round(main_h * 0.65f);
            float mem_h     = main_h - asm_h;
            float reg_h     = std::round(main_h * 0.28f);
            float disasm_h  = std::round(main_h * 0.40f);
            float serial_h  = std::round(main_h * 0.16f);
            float memmap_h  = main_h - reg_h - disasm_h - serial_h;

            ImGui::SetNextWindowPos({0,      0},                                  layout_cond);
            ImGui::SetNextWindowSize({W,      ctrl_h},                             layout_cond);
            if (control_panel) control_panel->render();

            ImGui::SetNextWindowPos({0,      ctrl_h},                              layout_cond);
            ImGui::SetNextWindowSize({left_w, asm_h},                              layout_cond);
            if (assembler_panel) assembler_panel->render();

            ImGui::SetNextWindowPos({0,      ctrl_h + asm_h},                     layout_cond);
            ImGui::SetNextWindowSize({left_w, mem_h},                              layout_cond);
            if (memory_panel) memory_panel->render();

            ImGui::SetNextWindowPos({left_w, ctrl_h},                              layout_cond);
            ImGui::SetNextWindowSize({right_w, reg_h},                             layout_cond);
            if (register_panel) register_panel->render();

            ImGui::SetNextWindowPos({left_w, ctrl_h + reg_h},                     layout_cond);
            ImGui::SetNextWindowSize({right_w, disasm_h},                          layout_cond);
            if (disassembly_panel) disassembly_panel->render();

            ImGui::SetNextWindowPos({left_w, ctrl_h + reg_h + disasm_h},          layout_cond);
            ImGui::SetNextWindowSize({right_w, serial_h},                          layout_cond);
            if (serial_output_panel) serial_output_panel->render();

            ImGui::SetNextWindowPos({left_w, ctrl_h + reg_h + disasm_h + serial_h}, layout_cond);
            ImGui::SetNextWindowSize({right_w, memmap_h},                          layout_cond);
            if (memmap_panel) memmap_panel->render();

            // Rendering
            ImGui::Render();

            // Clear and render
            glViewport(0, 0, fb_w, fb_h);
            glClearColor(0.10f, 0.10f, 0.10f, 1.00f);
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

            ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());

            SDL_GL_SwapWindow(window);
        } catch (const std::exception& e) {
            std::cerr << "Frame render error: " << e.what() << "\n";
            running = false;
        }
    }
}

void App::shutdown() {
    if (shutdown_done) return;
    shutdown_done = true;

    // Save last edited file
    saveLastFile();

    // Cleanup panels
    assembler_panel.reset();
    disassembly_panel.reset();
    register_panel.reset();
    memory_panel.reset();
    serial_output_panel.reset();
    memmap_panel.reset();

    // Cleanup ImGui
    if (ImGui::GetCurrentContext()) {
        ImGui_ImplOpenGL3_Shutdown();
        ImGui_ImplSDL2_Shutdown();
        ImGui::DestroyContext();
    }

    // Cleanup SDL2
    if (gl_ctx) {
        SDL_GL_DeleteContext(gl_ctx);
        gl_ctx = nullptr;
    }
    if (window) {
        SDL_DestroyWindow(window);
        window = nullptr;
    }
    if (SDL_WasInit(SDL_INIT_VIDEO)) {
        SDL_Quit();
    }

    // Cleanup NFD
    NFD_Quit();
}

void App::updateSerialOutput() {
    drainSerialToBuffer(state.emulator, state.serial_output);
}

std::string App::configDir() const {
    const char* home = std::getenv("HOME");
    if (!home) return ".";
    return std::string(home) + "/.config/little-64";
}

std::string App::imguiIniPath() const {
    return configDir() + "/imgui.ini";
}

std::string App::projectLayoutPath() const {
    if (state.project_path.empty()) return {};
    std::filesystem::path p(state.project_path);
    return (p.parent_path() / ".little64" / "imgui.ini").string();
}

void App::ensureConfigDir() {
    std::filesystem::create_directories(configDir());
}

void App::applyUIScale() {
    state.ui_scale = std::clamp(state.ui_scale, 0.75f, 2.5f);
    ImGui::StyleColorsDark();
    ImGui::GetStyle().ScaleAllSizes(state.ui_scale);
    ImGui::GetIO().FontGlobalScale = state.ui_scale;
}

void App::rebuildFonts() {
    ImGuiIO& io = ImGui::GetIO();
    io.Fonts->Clear();
    state.editor_fonts.clear();

    const char* font_path = findSystemMonoFont();
    if (font_path) {
        for (float sz : kEditorFontSizes) {
            ImFont* f = io.Fonts->AddFontFromFileTTF(font_path, sz);
            state.editor_fonts.push_back(f);
        }
    } else {
        for (size_t i = 0; i < kEditorFontSizes.size(); ++i)
            state.editor_fonts.push_back(nullptr);
    }

    if (state.editor_font_idx < 0 || state.editor_font_idx >= (int)state.editor_fonts.size()) {
        state.editor_font_idx = 3;
    }

    if (!state.editor_fonts.empty() && state.editor_fonts[3]) {
        io.FontDefault = state.editor_fonts[3];
    } else {
        io.FontDefault = io.Fonts->AddFontDefault();
    }
}

void App::loadLastFile() {
    // Read config path: ~/.config/little-64/last_file
    const char* home = std::getenv("HOME");
    if (!home) return;

    std::string config_path = configDir() + "/last_file";
    std::ifstream config_file(config_path);
    if (!config_file.is_open()) return;

    std::string path;
    if (!std::getline(config_file, path) || path.empty()) return;

    // Check the file exists before committing to it
    std::ifstream check_file(path);
    if (!check_file.is_open()) return;

    state.current_file = path;
    // AssemblerPanel constructor reads state.current_file and opens the file
    // (or project if the path ends in .l64proj).
}

void App::saveLastFile() {
    // Prefer project path so reopening restores the full project
    const std::string& path = state.project_path.empty()
                              ? state.current_file : state.project_path;
    if (path.empty()) return;

    const char* home = std::getenv("HOME");
    if (!home) return;

    std::string config_path = configDir() + "/last_file";
    ensureConfigDir();

    std::ofstream config_file(config_path);
    if (config_file.is_open())
        config_file << path;
}
