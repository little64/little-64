#include "assembler.hpp"
#include <iostream>
#include <fstream>
#include <sstream>
#include <cstring>
#include <iomanip>

void printUsage(const char* prog_name) {
    std::cerr << "Usage: " << prog_name << " [options] <input.asm>\n"
              << "Options:\n"
              << "  -o <file>     Output file (default: input.bin)\n"
              << "  --list        Print instruction listing to stdout\n"
              << "  --hex         Output as Intel HEX format\n";
}

int main(int argc, char* argv[]) {
    std::string input_file;
    std::string output_file;
    bool print_list = false;
    bool hex_output = false;

    // Parse arguments
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "-o") == 0) {
            if (i + 1 >= argc) {
                std::cerr << "Error: -o requires an argument\n";
                printUsage(argv[0]);
                return 1;
            }
            output_file = argv[++i];
        } else if (std::strcmp(argv[i], "--list") == 0) {
            print_list = true;
        } else if (std::strcmp(argv[i], "--hex") == 0) {
            hex_output = true;
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

    // Read input file
    std::ifstream in(input_file);
    if (!in) {
        std::cerr << "Error: Cannot open input file: " << input_file << "\n";
        return 1;
    }

    std::string source((std::istreambuf_iterator<char>(in)),
                       std::istreambuf_iterator<char>());
    in.close();

    // Determine output file name if not specified
    if (output_file.empty()) {
        output_file = input_file;
        size_t dot_pos = output_file.rfind('.');
        if (dot_pos != std::string::npos) {
            output_file = output_file.substr(0, dot_pos);
        }
        output_file += ".bin";
    }

    // Assemble
    Assembler assembler;
    std::vector<uint16_t> binary;

    try {
        binary = assembler.assemble(source);
    } catch (const std::exception& e) {
        std::cerr << "Assembly error: " << e.what() << "\n";
        return 1;
    }

    // Output listing if requested
    if (print_list) {
        std::cout << assembler.getListing();
    }

    // Write binary output
    std::ofstream out(output_file, std::ios::binary);
    if (!out) {
        std::cerr << "Error: Cannot open output file: " << output_file << "\n";
        return 1;
    }

    // Write as little-endian 16-bit words
    for (uint16_t word : binary) {
        uint8_t lo = word & 0xFF;
        uint8_t hi = (word >> 8) & 0xFF;
        out.put(lo);
        out.put(hi);
    }

    out.close();
    std::cout << "Assembled " << binary.size() << " instructions to " << output_file << "\n";

    return 0;
}
