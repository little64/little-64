#include "app.hpp"
#include "panels/assembler_panel.hpp"
#include "panels/control_panel.hpp"
#include "panels/disassembly_panel.hpp"
#include "panels/register_panel.hpp"
#include "panels/memory_panel.hpp"
#include "panels/serial_output_panel.hpp"
#include "panels/memmap_panel.hpp"

#include "../emulator/serial_device.hpp"
#include <SDL2/SDL.h>
#include <GL/gl.h>
#include <imgui.h>
#include <imgui_impl_sdl2.h>
#include <imgui_impl_opengl3.h>
#include <nfd.h>
#include <iostream>
#include <fstream>
#include <sys/stat.h>
#include <cmath>
#include <cstring>

App::App() {}

App::~App() {
    shutdown();
}

bool App::init() {
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
        SDL_WINDOW_OPENGL | SDL_WINDOW_RESIZABLE | SDL_WINDOW_SHOWN
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

    ImGui::StyleColorsDark();

    // Load multiple sizes of the monospace TTF for the resizable editor.
    // Index 3 (16px) is the default and is also used as the global UI font.
    static const float kEditorFontSizes[] = {10.0f, 12.0f, 14.0f, 16.0f, 18.0f, 20.0f, 24.0f};
    const char* font_path = "/usr/share/fonts/truetype/DejaVuSansMono.ttf";
    for (float sz : kEditorFontSizes) {
        ImFont* f = io.Fonts->AddFontFromFileTTF(font_path, sz);
        state.editor_fonts.push_back(f);
    }
    // Use the 16px entry as the global UI font; fall back to built-in default if TTF is missing.
    if (state.editor_fonts[3])
        io.FontDefault = state.editor_fonts[3];
    else
        io.Fonts->AddFontDefault();

    // Setup ImGui SDL2 backend
    ImGui_ImplSDL2_InitForOpenGL(window, gl_ctx);

    // Setup ImGui OpenGL3 backend
    const char* glsl_version = "#version 330 core";
    ImGui_ImplOpenGL3_Init(glsl_version);

    // Load last edited file into state before constructing panels
    loadLastFile();

    // Initialize panels
    assembler_panel     = std::make_unique<AssemblerPanel>(state);
    control_panel       = std::make_unique<ControlPanel>(state);
    disassembly_panel   = std::make_unique<DisassemblyPanel>(state);
    register_panel      = std::make_unique<RegisterPanel>(state);
    memory_panel        = std::make_unique<MemoryPanel>(state);
    serial_output_panel = std::make_unique<SerialOutputPanel>(state);
    memmap_panel        = std::make_unique<MemoryMapPanel>(state);

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
                default:
                    break;
            }
        }

        try {
            // Start ImGui frame
            ImGui_ImplOpenGL3_NewFrame();
            ImGui_ImplSDL2_NewFrame();
            ImGui::NewFrame();

            updateSerialOutput();

            // Fixed layout: tile all panels to fill the window
            float W = io.DisplaySize.x;
            float H = io.DisplaySize.y;
            const float ctrl_h  = 90.0f;
            float left_w  = std::round(W * 0.55f);
            float right_w = W - left_w;
            float main_h  = H - ctrl_h;
            float asm_h     = std::round(main_h * 0.65f);
            float mem_h     = main_h - asm_h;
            float reg_h     = std::round(main_h * 0.28f);
            float disasm_h  = std::round(main_h * 0.40f);
            float serial_h  = std::round(main_h * 0.16f);
            float memmap_h  = main_h - reg_h - disasm_h - serial_h;

            ImGui::SetNextWindowPos({0,      0},                                  ImGuiCond_Always);
            ImGui::SetNextWindowSize({W,      ctrl_h},                             ImGuiCond_Always);
            if (control_panel) control_panel->render();

            ImGui::SetNextWindowPos({0,      ctrl_h},                              ImGuiCond_Always);
            ImGui::SetNextWindowSize({left_w, asm_h},                              ImGuiCond_Always);
            if (assembler_panel) assembler_panel->render();

            ImGui::SetNextWindowPos({0,      ctrl_h + asm_h},                     ImGuiCond_Always);
            ImGui::SetNextWindowSize({left_w, mem_h},                              ImGuiCond_Always);
            if (memory_panel) memory_panel->render();

            ImGui::SetNextWindowPos({left_w, ctrl_h},                              ImGuiCond_Always);
            ImGui::SetNextWindowSize({right_w, reg_h},                             ImGuiCond_Always);
            if (register_panel) register_panel->render();

            ImGui::SetNextWindowPos({left_w, ctrl_h + reg_h},                     ImGuiCond_Always);
            ImGui::SetNextWindowSize({right_w, disasm_h},                          ImGuiCond_Always);
            if (disassembly_panel) disassembly_panel->render();

            ImGui::SetNextWindowPos({left_w, ctrl_h + reg_h + disasm_h},          ImGuiCond_Always);
            ImGui::SetNextWindowSize({right_w, serial_h},                          ImGuiCond_Always);
            if (serial_output_panel) serial_output_panel->render();

            ImGui::SetNextWindowPos({left_w, ctrl_h + reg_h + disasm_h + serial_h}, ImGuiCond_Always);
            ImGui::SetNextWindowSize({right_w, memmap_h},                          ImGuiCond_Always);
            if (memmap_panel) memmap_panel->render();

            // Rendering
            ImGui::Render();

            // Clear and render
            glViewport(0, 0, (int)io.DisplaySize.x, (int)io.DisplaySize.y);
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
    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplSDL2_Shutdown();
    ImGui::DestroyContext();

    // Cleanup SDL2
    if (gl_ctx) {
        SDL_GL_DeleteContext(gl_ctx);
        gl_ctx = nullptr;
    }
    if (window) {
        SDL_DestroyWindow(window);
        window = nullptr;
    }
    SDL_Quit();

    // Cleanup NFD
    NFD_Quit();
}

void App::updateSerialOutput() {
    SerialDevice* serial = state.cpu.getSerial();
    if (!serial) return;
    const std::string& buf = serial->txBuffer();
    if (!buf.empty()) {
        state.serial_output += buf;
        serial->clearTxBuffer();
    }
}

void App::loadLastFile() {
    // Read config path: ~/.config/little-64/last_file
    const char* home = std::getenv("HOME");
    if (!home) return;

    std::string config_path = std::string(home) + "/.config/little-64/last_file";
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

    std::string config_dir = std::string(home) + "/.config/little-64";
    std::string config_path = config_dir + "/last_file";

    mkdir(config_dir.c_str(), 0755);

    std::ofstream config_file(config_path);
    if (config_file.is_open())
        config_file << path;
}
