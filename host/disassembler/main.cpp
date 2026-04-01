#include "disassembler.hpp"
#include <iostream>
#include <fstream>
#include <cstring>
#include <iomanip>
#include <vector>

void printUsage(const char* prog_name) {
    std::cerr << "Usage: " << prog_name << " [options] <input.bin>\n"
              << "Options:\n"
              << "  --base <addr>   Starting address in hex (default: 0x0000)\n"
              << "  --count <n>     Number of instructions to disassemble (default: all)\n"
              << "  --no-hex        Suppress raw hex column\n";
}

int main(int argc, char* argv[]) {
    std::string input_file;
    uint16_t base_address = 0;
    size_t count = 0;  // 0 means all
    bool show_hex = true;

    // Parse arguments
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--base") == 0) {
            if (i + 1 >= argc) {
                std::cerr << "Error: --base requires an argument\n";
                printUsage(argv[0]);
                return 1;
            }
            try {
                base_address = std::stoi(argv[++i], nullptr, 16);
            } catch (...) {
                std::cerr << "Error: Invalid hex address\n";
                return 1;
            }
        } else if (std::strcmp(argv[i], "--count") == 0) {
            if (i + 1 >= argc) {
                std::cerr << "Error: --count requires an argument\n";
                printUsage(argv[0]);
                return 1;
            }
            try {
                count = std::stoul(argv[++i]);
            } catch (...) {
                std::cerr << "Error: Invalid count\n";
                return 1;
            }
        } else if (std::strcmp(argv[i], "--no-hex") == 0) {
            show_hex = false;
        } else if (argv[i][0] == '-') {
            std::cerr << "Error: Unknown option " << argv[i] << "\n";
            printUsage(argv[0]);
            return 1;
        } else {
            input_file = argv[i];
        }
    }

    if (input_file.empty()) {
        std::cerr << "Error: No input file specified\n";
        printUsage(argv[0]);
        return 1;
    }

    // Read input file as little-endian 16-bit words
    std::ifstream in(input_file, std::ios::binary);
    if (!in) {
        std::cerr << "Error: Cannot open input file: " << input_file << "\n";
        return 1;
    }

    std::vector<uint16_t> words;
    uint8_t lo, hi;
    while (in.read(reinterpret_cast<char*>(&lo), 1)) {
        if (!in.read(reinterpret_cast<char*>(&hi), 1)) {
            std::cerr << "Warning: Incomplete final instruction (odd number of bytes)\n";
            break;
        }
        words.push_back((static_cast<uint16_t>(hi) << 8) | lo);
    }
    in.close();

    if (words.empty()) {
        std::cerr << "Error: No data in input file\n";
        return 1;
    }

    // Limit to requested count
    if (count > 0 && count < words.size()) {
        words.resize(count);
    }

    // Disassemble
    std::vector<DisassembledInstruction> disassembly =
        Disassembler::disassembleBuffer(words.data(), words.size(), base_address);

    // Print output
    std::cout << std::hex << std::setfill('0');
    for (const auto& instr : disassembly) {
        std::cout << "0x" << std::setw(4) << instr.address;
        if (show_hex) {
            std::cout << "  " << std::setw(4) << instr.raw;
        }
        std::cout << "  " << instr.text << "\n";
    }

    return 0;
}
