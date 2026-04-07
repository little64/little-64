#include "debug_server.hpp"
#include "debug_transport.hpp"
#include "emulator_session.hpp"
#include "headless_runtime.hpp"

#include <cstdint>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
    uint16_t port = 9000;
    std::string image_path;
    HeadlessLoadOptions load_options;

    // Parse optional flags, then positional: [port] [image]
    int positional = 0;
    for (int i = 1; i < argc; ++i) {
        const std::string arg(argv[i]);
        if (arg.rfind("--boot-mode=", 0) == 0) {
            const std::string mode = arg.substr(std::string("--boot-mode=").size());
            if (mode == "auto")    load_options.boot_mode = HeadlessBootMode::Auto;
            else if (mode == "bios")   load_options.boot_mode = HeadlessBootMode::Bios;
            else if (mode == "direct") load_options.boot_mode = HeadlessBootMode::Direct;
            else {
                std::cerr << "Error: invalid --boot-mode value '" << mode << "'\n";
                return 2;
            }
            continue;
        }
        if (positional == 0) {
            try {
                const unsigned long parsed = std::stoul(arg, nullptr, 10);
                if (parsed > 0 && parsed <= 65535)
                    port = static_cast<uint16_t>(parsed);
            } catch (...) {
                std::cerr << "Error: expected port number, got '" << arg << "'\n";
                return 2;
            }
            ++positional;
        } else if (positional == 1) {
            image_path = arg;
            ++positional;
        }
    }

    EmulatorSession runtime;
    if (!image_path.empty()) {
        std::string error;
        if (!loadRuntimeImageFromPath(runtime, image_path, error, load_options)) {
            std::cerr << error << '\n';
            return 2;
        }
    }

    TcpRspTransport transport(port);
    DebugServer server(runtime, transport);
    return server.run();
}
