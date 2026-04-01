#pragma once

#include <string>
#include <vector>
#include <cstdint>

struct Expectation {
    enum class Type { Register, Memory } type;
    int      reg_idx;         // Type::Register — index 0-15
    uint64_t mem_addr;        // Type::Memory
    uint64_t expected_value;
    std::string source_file;
    int line_number;
};

struct ProjectFile {
    std::string path;   // absolute path to .l64proj file
    std::string dir;    // directory containing the project file
    std::string name;   // project name (derived from filename)

    std::vector<std::string>  sources;       // absolute source paths, in order
    std::vector<Expectation>  expectations;  // from "; EXPECT" comments in all sources

    // Load a project from a .l64proj file.
    // Resolves source paths relative to the project file's directory.
    // Scans all sources for "; EXPECT" assertions.
    // Throws std::runtime_error on I/O or parse failure.
    static ProjectFile load(const std::string& path);

    // Write the current sources list back to the .l64proj file.
    // Paths are written as relative to the project directory.
    // Throws std::runtime_error if the file cannot be written.
    void save() const;
};
