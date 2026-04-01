#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

class LLVMAssembler {
public:
    static std::optional<std::vector<uint8_t>> assembleSourceFile(
        const std::string& source_path,
        std::string& error);

    static std::optional<std::vector<uint8_t>> assembleSourceText(
        const std::string& source_text,
        const std::string& filename_hint,
        std::string& error);
};
