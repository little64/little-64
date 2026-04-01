#include "project.hpp"
#include "compiler.hpp"
#include "llvm_assembler.hpp"
#include "linker.hpp"
#include "emulator_session.hpp"
#include <iostream>
#include <fstream>
#include <cstdio>

int main(int argc, char* argv[]) {
    std::string proj_path;
    uint64_t max_cycles = 1000000;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--max-cycles" && i + 1 < argc) {
            try {
                max_cycles = std::stoull(argv[++i]);
            } catch (...) {
                std::cerr << "Invalid --max-cycles value\n";
                return 1;
            }
        } else {
            proj_path = arg;
        }
    }

    if (proj_path.empty()) {
        std::cerr << "Usage: " << argv[0] << " <project.l64proj> [--max-cycles N]\n";
        return 1;
    }

    // Load project file
    ProjectFile proj;
    try {
        proj = ProjectFile::load(proj_path);
    } catch (const std::exception& e) {
        std::cerr << "Error loading project: " << e.what() << "\n";
        return 1;
    }

    if (proj.sources.empty()) {
        std::cerr << "Project has no source files\n";
        return 1;
    }

    // Assemble (via llvm-mc) or compile each source as an ELF object
    std::vector<std::vector<uint8_t>> objects;
    for (const auto& src_path : proj.sources) {
        std::string ext;
        auto dot = src_path.find_last_of('.') ;
        if (dot != std::string::npos) {
            ext = src_path.substr(dot + 1);
            std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c){ return std::tolower(c); });
        }

        if (ext == "c" || ext == "cpp" || ext == "cc") {
            std::string compile_err;
            bool is_cpp = (ext == "cpp" || ext == "cc");
            auto compiled = Compiler::compileSourceFile(src_path, is_cpp, "0", compile_err);
            if (!compiled) {
                std::cerr << "Compiler error in " << src_path << ": " << compile_err << "\n";
                return 1;
            }
            objects.push_back(std::move(*compiled));
            continue;
        }

        std::string asm_error;
        auto assembled = LLVMAssembler::assembleSourceFile(src_path, asm_error);
        if (!assembled) {
            std::cerr << "Assembly error in " << src_path << ": " << asm_error << "\n";
            return 1;
        }
        objects.push_back(std::move(*assembled));
    }

    // Link
    LinkError link_err;
    bool useElfLoader = true;
    const char* loadElfEnv = std::getenv("LITTLE64_LOAD_ELF");
    if (loadElfEnv && loadElfEnv[0] == '0')
        useElfLoader = false;

    EmulatorSession runtime;

    if (useElfLoader) {
        auto elf_image = Linker::linkObjectsElf(objects, &link_err);
        if (!elf_image) {
            std::cerr << "Link error (ELF): " << link_err.message << "\n";
            return 1;
        }
        if (!runtime.loadProgramElf(*elf_image, 0)) {
            std::cerr << "CPU ELF load failed\n";
            return 1;
        }
    } else {
        auto linked = Linker::linkObjects(objects, &link_err);
        if (!linked) {
            std::cerr << "Link error: " << link_err.message << "\n";
            return 1;
        }
        uint64_t entry_offset = link_err.has_entry ? link_err.entry_address : 0;
        runtime.loadProgram(*linked, 0, entry_offset);
    }

    if (proj.expectations.empty()) {
        std::cout << "Assembled and linked successfully (no EXPECT assertions).\n";
        return 0;
    }

    uint64_t cycles = 0;
    while (runtime.isRunning() && cycles < max_cycles) {
        runtime.cycle();
        ++cycles;
    }

    if (runtime.isRunning()) {
        std::cerr << "FAIL: program did not halt after " << max_cycles << " cycles\n";
        return 1;
    }

    // Check EXPECT assertions
    int failures = 0;
    for (const auto& exp : proj.expectations) {
        uint64_t actual = 0;
        char target_buf[64];

        if (exp.type == Expectation::Type::Register) {
            actual = runtime.reg(exp.reg_idx);
            std::snprintf(target_buf, sizeof(target_buf), "R%d", exp.reg_idx);
        } else {
            actual = runtime.memoryRead8(exp.mem_addr);
            std::snprintf(target_buf, sizeof(target_buf), "mem:0x%llX",
                          static_cast<unsigned long long>(exp.mem_addr));
        }

        if (actual == exp.expected_value) {
            std::cout << "PASS  " << target_buf
                      << " = " << exp.expected_value << "\n";
        } else {
            std::cerr << "FAIL  " << target_buf
                      << " expected " << exp.expected_value
                      << " got " << actual
                      << "  (" << exp.source_file << ":" << exp.line_number << ")\n";
            ++failures;
        }
    }

    return failures > 0 ? 1 : 0;
}
