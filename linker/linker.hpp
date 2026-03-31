#pragma once

#include <cstdint>
#include <string>
#include <vector>
#include <optional>

struct LinkError {
    std::string message;
    uint64_t entry_address = 0;
    bool has_entry = false;
};

class Linker {
public:
    // Link ELF object blobs into a flat program binary as 16-bit words.
    // Returns nullopt on failure, or vector of words on success.
    static std::optional<std::vector<uint16_t>> linkObjects(const std::vector<std::vector<uint8_t>>& objects, LinkError* err = nullptr);

    // Link ELF object blobs into an ELF image using ld.lld.
    // Returns nullopt on failure, or ELF bytes on success.
    static std::optional<std::vector<uint8_t>> linkObjectsElf(const std::vector<std::vector<uint8_t>>& objects, LinkError* err = nullptr);
};
