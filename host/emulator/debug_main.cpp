#include "debug_server.hpp"
#include "debug_transport.hpp"
#include "disk_image.hpp"
#include "emulator_session.hpp"
#include "headless_runtime.hpp"

#include <cstdint>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
    uint16_t port = 9000;
    std::string image_path;
    std::string disk_path;
    bool disk_read_only = false;
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
            else if (mode == "litex-bootrom") load_options.boot_mode = HeadlessBootMode::LiteXBootRom;
            else if (mode == "litex-flash") load_options.boot_mode = HeadlessBootMode::LiteXFlash;
            else {
                std::cerr << "Error: invalid --boot-mode value '" << mode << "'\n";
                return 2;
            }
            continue;
        }
        if (arg.rfind("--disk=", 0) == 0) {
            disk_path = arg.substr(std::string("--disk=").size());
            if (disk_path.empty()) {
                std::cerr << "Error: --disk requires a non-empty path\n";
                return 2;
            }
            continue;
        }
        if (arg == "--disk-readonly") {
            disk_read_only = true;
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
    if (!disk_path.empty()) {
        auto disk = DiskImage::open(disk_path, disk_read_only);
        if (!disk || !disk->isValid() || !disk->lastError().empty()) {
            std::cerr << "Error: failed to attach disk image: "
                      << (disk ? disk->lastError() : std::string("unknown error")) << '\n';
            return 2;
        }
        runtime.setDiskImage(std::move(disk));
    }
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
