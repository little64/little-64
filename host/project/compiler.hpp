#pragma once

#include <cstdint>
#include <string>
#include <vector>
#include <optional>

class Compiler {
public:
    // Compile a disk-backed source file into an ELF object blob.
    // `is_cpp` selects C++ mode (true) or C mode (false).
    // Returns std::nullopt on failure with `error` set.
    static std::optional<std::vector<uint8_t>> compileSourceFile(
        const std::string& source_path,
        bool is_cpp,
        const std::string& opt_level,
        std::string& error);

    // Compile an in-memory source string as C or C++ and return object blob.
    static std::optional<std::vector<uint8_t>> compileSourceText(
        const std::string& source_text,
        const std::string& filename_hint,
        bool is_cpp,
        const std::string& opt_level,
        std::string& error);
};
