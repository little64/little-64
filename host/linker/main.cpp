#include "linker.hpp"
#include <iostream>
#include <fstream>
#include <vector>

static std::vector<uint8_t> readFile(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) return {};
    std::vector<uint8_t> data((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    return data;
}

int main(int argc, char* argv[]) {
    if (argc < 3) {
        std::cerr << "Usage: " << argv[0] << " -o <output.bin> <input1.o> [<input2.o> ...]\n";
        return 1;
    }

    std::string out_path;
    std::vector<std::string> in_paths;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "-o" && i + 1 < argc) {
            out_path = argv[++i];
        } else {
            in_paths.push_back(arg);
        }
    }

    if (out_path.empty() || in_paths.empty()) {
        std::cerr << "Missing output or inputs\n";
        return 1;
    }

    std::vector<std::vector<uint8_t>> objects;
    for (auto& p : in_paths) {
        auto obj = readFile(p);
        if (obj.empty()) {
            std::cerr << "Cannot read " << p << "\n";
            return 1;
        }
        objects.push_back(std::move(obj));
    }

    LinkError err;
    auto linked = Linker::linkObjects(objects, &err);
    if (!linked) {
        std::cerr << "Link error: " << err.message << "\n";
        return 1;
    }

    std::ofstream out(out_path, std::ios::binary);
    if (!out) {
        std::cerr << "Cannot open output file: " << out_path << "\n";
        return 1;
    }

    for (uint16_t w : *linked) {
        out.put(static_cast<char>(w & 0xFF));
        out.put(static_cast<char>((w >> 8) & 0xFF));
    }

    return 0;
}
