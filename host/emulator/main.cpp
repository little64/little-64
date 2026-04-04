#include "emulator_session.hpp"
#include "headless_runtime.hpp"
#include <iostream>
#include <string>

static void printUsage(const char* argv0) {
    std::cerr << "Usage: " << argv0 << " [--boot-mode=auto|bios|direct] <binary.bin|object.o>\n"
              << "  Runs the assembled binary/ELF object and prints any serial (UART) output to stdout.\n";
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        printUsage(argv[0]);
        return 1;
    }

    HeadlessLoadOptions load_options;
    std::string image_path;

    for (int i = 1; i < argc; ++i) {
        const std::string arg(argv[i]);
        if (arg.rfind("--boot-mode=", 0) == 0) {
            const std::string mode = arg.substr(std::string("--boot-mode=").size());
            if (mode == "auto") load_options.boot_mode = HeadlessBootMode::Auto;
            else if (mode == "bios") load_options.boot_mode = HeadlessBootMode::Bios;
            else if (mode == "direct") load_options.boot_mode = HeadlessBootMode::Direct;
            else {
                std::cerr << "Error: invalid --boot-mode value '" << mode << "'\n";
                printUsage(argv[0]);
                return 1;
            }
            continue;
        }

        if (!image_path.empty()) {
            std::cerr << "Error: multiple image paths provided\n";
            printUsage(argv[0]);
            return 1;
        }
        image_path = arg;
    }

    if (image_path.empty()) {
        printUsage(argv[0]);
        return 1;
    }

    EmulatorSession runtime;
    std::string error;
    if (!loadRuntimeImageFromPath(runtime, image_path, error, load_options)) {
        std::cerr << error << "\n";
        return 1;
    }

    HeadlessRunOptions options;
    if (runRuntimeUntilStop(runtime, options, error) != 0) {
        std::cerr << error << "\n";
        return 1;
    }

    return 0;
}
