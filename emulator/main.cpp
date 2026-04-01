#include "emulator_session.hpp"
#include "headless_runtime.hpp"
#include <iostream>
#include <string>

static void printUsage(const char* argv0) {
    std::cerr << "Usage: " << argv0 << " <binary.bin|object.o>\n"
              << "  Runs the assembled binary/ELF object and prints any serial (UART) output to stdout.\n";
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        printUsage(argv[0]);
        return 1;
    }

    EmulatorSession runtime;
    std::string error;
    if (!loadRuntimeImageFromPath(runtime, argv[1], error)) {
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
