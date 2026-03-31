#include "compiler.hpp"
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <system_error>
#include <vector>
#include <array>

#if defined(_WIN32)
#include <io.h>
#define access _access
#define F_OK 0
#define X_OK 1
#else
#include <unistd.h>
#endif

static std::string toLower(std::string s) {
    for (auto& c : s) c = static_cast<char>(std::tolower(c));
    return s;
}

static std::string shellQuote(const std::string& s) {
    std::string out = "'";
    for (char c : s) {
        if (c == '\'') out += "'\\''";
        else out.push_back(c);
    }
    out += "'";
    return out;
}

static bool fileExists(const std::string& path) {
    return std::filesystem::exists(std::filesystem::path(path));
}

static bool isExecutable(const std::string& path) {
    if (!fileExists(path)) return false;
#if defined(_WIN32)
    // assume user supplied valid executable path
    return true;
#else
    return (access(path.c_str(), X_OK) == 0);
#endif
}

static std::string chooseCompiler(bool is_cpp) {
    const char* env = is_cpp ? std::getenv("LITTLE64_CXX") : std::getenv("LITTLE64_CC");
    if (env && env[0]) return env;

    // Prefer the right driver for the language so that C++ headers and language
    // modes work correctly.  Fall back to the other driver only if the preferred
    // one is absent (both can compile with the explicit --std= flag we pass).
    std::vector<std::string> candidates;
    if (is_cpp) {
        candidates = {
            "compilers/bin/clang++",
            "compilers/bin/clang",
            "clang++",
            "clang"
        };
    } else {
        candidates = {
            "compilers/bin/clang",
            "clang"
        };
    }

    for (const auto& c : candidates) {
        // allow relative path to project root when the app is started from within repo
        if (isExecutable(c))
            return c;
        std::filesystem::path p = std::filesystem::current_path() / c;
        if (isExecutable(p.string()))
            return p.string();
    }

    return {};
}

static std::optional<std::vector<uint8_t>> runCompileCommand(const std::string& command,
                                                              const std::filesystem::path& out_path,
                                                              std::string& error) {
    std::string cmd = command + " 2>&1";
    std::array<char, 512> buf;
    std::string output;
    FILE* pipe = popen(cmd.c_str(), "r");
    if (!pipe) {
        error = "Failed to run compiler command";
        return std::nullopt;
    }
    while (fgets(buf.data(), static_cast<int>(buf.size()), pipe) != nullptr) {
        output += buf.data();
    }
    int status = pclose(pipe);
    if (status != 0) {
        std::ostringstream ss;
        ss << "Compiler exited with status " << status << ".\n" << output;
        error = ss.str();
        return std::nullopt;
    }

    // Read generated object
    std::ifstream obj(out_path, std::ios::binary);
    if (!obj.is_open()) {
        error = "Compiler succeeded but cannot open object file: " + out_path.string();
        return std::nullopt;
    }
    std::vector<uint8_t> obj_data((std::istreambuf_iterator<char>(obj)),
                                  std::istreambuf_iterator<char>());
    return obj_data;
}

static bool isValidOptLevel(const std::string& lv) {
    return lv == "0" || lv == "1" || lv == "2" || lv == "3" || lv == "s" || lv == "z";
}

std::optional<std::vector<uint8_t>> Compiler::compileSourceFile(const std::string& source_path,
                                                                bool is_cpp,
                                                                const std::string& opt_level,
                                                                std::string& error)
{
    if (!isValidOptLevel(opt_level)) {
        error = "Invalid optimization level: " + opt_level;
        return std::nullopt;
    }
    if (!fileExists(source_path)) {
        error = "Source file does not exist: " + source_path;
        return std::nullopt;
    }

    std::string compiler = chooseCompiler(is_cpp);
    if (compiler.empty()) {
        error = "No Little-64 C/C++ compiler found. Set LITTLE64_CC or LITTLE64_CXX environment variable to clang/clang++ on path.";
        return std::nullopt;
    }

    std::filesystem::path out_path = std::filesystem::temp_directory_path() / "little64_tmp_object.o";
    // Ensure unique-ish name
    static int counter = 0;
    out_path = out_path.parent_path() / ("little64_tmp_object_" + std::to_string(++counter) + ".o");

    std::string std_flag = is_cpp ? "--std=c++17" : "--std=c11";
    std::string opt_flag = "-O" + opt_level;
    std::string cmd = compiler + " --target=little64 -c -g " + opt_flag + " " + std_flag + " " +
                      shellQuote(source_path) + " -o " + shellQuote(out_path.string());

    auto result = runCompileCommand(cmd, out_path, error);
    std::filesystem::remove(out_path);
    return result;
}

std::optional<std::vector<uint8_t>> Compiler::compileSourceText(const std::string& source_text,
                                                                const std::string& filename_hint,
                                                                bool is_cpp,
                                                                const std::string& opt_level,
                                                                std::string& error)
{
    if (!isValidOptLevel(opt_level)) {
        error = "Invalid optimization level: " + opt_level;
        return std::nullopt;
    }
    std::filesystem::path tmp_source = std::filesystem::temp_directory_path() / "little64_tmp_source";
    tmp_source = tmp_source.parent_path() / (tmp_source.filename().string() + "." + (is_cpp ? "cpp" : "c"));

    static int counter = 0;
    tmp_source = tmp_source.parent_path() / ("little64_tmp_source_" + std::to_string(++counter) + (is_cpp ? ".cpp" : ".c"));

    std::ofstream f(tmp_source, std::ios::binary);
    if (!f.is_open()) {
        error = "Cannot write temporary source file: " + tmp_source.string();
        return std::nullopt;
    }
    f << source_text;
    f.close();

    auto result = compileSourceFile(tmp_source.string(), is_cpp, opt_level, error);
    std::filesystem::remove(tmp_source);
    return result;
}
