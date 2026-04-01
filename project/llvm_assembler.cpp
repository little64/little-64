#include "llvm_assembler.hpp"

#include <array>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

#if defined(_WIN32)
#include <io.h>
#include <process.h>
#define access _access
#define F_OK 0
#define X_OK 1
#else
#include <unistd.h>
#endif

namespace {

bool fileExists(const std::string& path) {
    return std::filesystem::exists(std::filesystem::path(path));
}

bool isExecutable(const std::string& path) {
    if (!fileExists(path)) return false;
#if defined(_WIN32)
    return true;
#else
    return (access(path.c_str(), X_OK) == 0);
#endif
}

std::string shellQuote(const std::string& s) {
    std::string out = "'";
    for (char c : s) {
        if (c == '\'') out += "'\\''";
        else out.push_back(c);
    }
    out += "'";
    return out;
}

std::optional<std::string> chooseLLVMMC() {
    const char* env = std::getenv("LITTLE64_AS");
    if (env && env[0] && isExecutable(env)) {
        return std::string(env);
    }

    const std::vector<std::string> candidates = {
        "compilers/bin/llvm-mc",
        "../compilers/bin/llvm-mc",
        "llvm-mc",
    };

    for (const auto& candidate : candidates) {
        if (isExecutable(candidate)) {
            return candidate;
        }
        std::filesystem::path absolute = std::filesystem::current_path() / candidate;
        if (isExecutable(absolute.string())) {
            return absolute.string();
        }
    }

    return std::nullopt;
}

std::string uniqueTempStem(const std::string& prefix) {
    static std::atomic<uint64_t> sequence{0};
    const auto now_ns = static_cast<uint64_t>(
        std::chrono::steady_clock::now().time_since_epoch().count());
#if defined(_WIN32)
    const uint64_t pid = static_cast<uint64_t>(_getpid());
#else
    const uint64_t pid = static_cast<uint64_t>(getpid());
#endif
    const uint64_t seq = sequence.fetch_add(1, std::memory_order_relaxed);
    return prefix + "_" + std::to_string(pid) + "_" + std::to_string(now_ns) + "_" + std::to_string(seq);
}

std::optional<std::vector<uint8_t>> runAssemblerCommand(
    const std::string& command,
    const std::filesystem::path& out_path,
    std::string& error) {
    const std::string cmd = command + " 2>&1";
    std::array<char, 512> buffer{};
    std::string output;

    FILE* pipe = popen(cmd.c_str(), "r");
    if (!pipe) {
        error = "Failed to run llvm-mc command";
        return std::nullopt;
    }

    while (fgets(buffer.data(), static_cast<int>(buffer.size()), pipe) != nullptr) {
        output += buffer.data();
    }

    const int status = pclose(pipe);
    if (status != 0) {
        std::ostringstream ss;
        ss << "llvm-mc failed with status " << status;
        if (!output.empty()) {
            ss << "\n" << output;
        }
        error = ss.str();
        return std::nullopt;
    }

    std::ifstream object_file(out_path, std::ios::binary);
    if (!object_file.is_open()) {
        error = "llvm-mc succeeded but object file was not created: " + out_path.string();
        return std::nullopt;
    }

    std::vector<uint8_t> data((std::istreambuf_iterator<char>(object_file)),
                              std::istreambuf_iterator<char>());
    if (data.empty()) {
        error = "llvm-mc produced an empty object file: " + out_path.string();
        return std::nullopt;
    }

    return data;
}

std::optional<std::vector<uint8_t>> assembleViaLLVMMC(
    const std::filesystem::path& source_path,
    std::string& error) {
    auto llvm_mc = chooseLLVMMC();
    if (!llvm_mc) {
        error = "No llvm-mc found. Set LITTLE64_AS or ensure compilers/bin/llvm-mc is available.";
        return std::nullopt;
    }

    auto out_path = std::filesystem::temp_directory_path() /
                    (uniqueTempStem("little64_tmp_asm") + ".o");

    const std::string command = *llvm_mc + " -triple=little64 -filetype=obj " +
                                shellQuote(source_path.string()) + " -o " +
                                shellQuote(out_path.string());

    auto result = runAssemblerCommand(command, out_path, error);
    std::filesystem::remove(out_path);
    return result;
}

} // namespace

std::optional<std::vector<uint8_t>> LLVMAssembler::assembleSourceFile(
    const std::string& source_path,
    std::string& error) {
    if (!fileExists(source_path)) {
        error = "Assembly source file does not exist: " + source_path;
        return std::nullopt;
    }
    return assembleViaLLVMMC(std::filesystem::path(source_path), error);
}

std::optional<std::vector<uint8_t>> LLVMAssembler::assembleSourceText(
    const std::string& source_text,
    const std::string& filename_hint,
    std::string& error) {
    std::string extension = ".asm";
    const auto dot = filename_hint.find_last_of('.');
    if (dot != std::string::npos) {
        extension = filename_hint.substr(dot);
        if (extension.empty()) {
            extension = ".asm";
        }
    }

    auto source_path = std::filesystem::temp_directory_path() /
                       (uniqueTempStem("little64_tmp_source") + extension);

    std::ofstream source_file(source_path, std::ios::binary);
    if (!source_file.is_open()) {
        error = "Cannot create temporary assembly source file: " + source_path.string();
        return std::nullopt;
    }
    source_file << source_text;
    source_file.close();

    auto result = assembleViaLLVMMC(source_path, error);
    std::filesystem::remove(source_path);
    return result;
}
