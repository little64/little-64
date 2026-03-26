#include "cpu.hpp"
#include "serial_device.hpp"
#include <iostream>
#include <fstream>
#include <vector>
#include <cstdint>
#include <cstring>

static void printUsage(const char* argv0) {
    std::cerr << "Usage: " << argv0 << " <binary.bin>\n"
              << "  Runs the assembled binary and prints any serial (UART) output to stdout.\n";
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        printUsage(argv[0]);
        return 1;
    }

    const char* path = argv[1];
    std::ifstream file(path, std::ios::binary);
    if (!file.is_open()) {
        std::cerr << "Error: cannot open '" << path << "'\n";
        return 1;
    }

    // Read file into byte buffer
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(file)),
                                std::istreambuf_iterator<char>());
    file.close();

    if (bytes.empty()) {
        std::cerr << "Error: file is empty\n";
        return 1;
    }

    // Pad to even length so we can reinterpret as uint16_t words
    if (bytes.size() % 2 != 0) bytes.push_back(0);

    // Reinterpret as little-endian 16-bit words
    std::vector<uint16_t> words(bytes.size() / 2);
    std::memcpy(words.data(), bytes.data(), bytes.size());

    Little64CPU cpu;
    cpu.loadProgram(words);

    SerialDevice* serial = cpu.getSerial();

    while (cpu.isRunning) {
        cpu.cycle();

        if (serial && !serial->txBuffer().empty()) {
            std::cout << serial->txBuffer() << std::flush;
            serial->clearTxBuffer();
        }
    }

    // Flush any remaining serial output
    if (serial && !serial->txBuffer().empty()) {
        std::cout << serial->txBuffer();
        serial->clearTxBuffer();
    }

    std::cout.flush();
    return 0;
}
