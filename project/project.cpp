#include "project.hpp"
#include <fstream>
#include <algorithm>
#include <cctype>
#include <stdexcept>

// ---------------------------------------------------------------------------
// String helpers
// ---------------------------------------------------------------------------

static std::string trim(const std::string& s) {
    size_t first = s.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return {};
    size_t last  = s.find_last_not_of(" \t\r\n");
    return s.substr(first, last - first + 1);
}

static std::string dirOf(const std::string& path) {
    size_t slash = path.find_last_of("/\\");
    return (slash == std::string::npos) ? "." : path.substr(0, slash);
}

static std::string stemOf(const std::string& path) {
    size_t slash = path.find_last_of("/\\");
    std::string base = (slash == std::string::npos) ? path : path.substr(slash + 1);
    size_t dot = base.rfind('.');
    return (dot == std::string::npos) ? base : base.substr(0, dot);
}

// ---------------------------------------------------------------------------
// EXPECT comment parser
// Format:  ; EXPECT <target> = <value>
//   target: R0..R15  or  mem:0xADDR  (case-insensitive for R/MEM prefix)
//   value:  decimal or 0x-prefixed hex
// ---------------------------------------------------------------------------

static bool parseExpect(const std::string& raw_line,
                        const std::string& source_file,
                        int lineno,
                        Expectation& out)
{
    // Make an uppercase copy for matching
    std::string up = raw_line;
    std::transform(up.begin(), up.end(), up.begin(), ::toupper);

    auto pos = up.find("; EXPECT");
    if (pos == std::string::npos) return false;

    std::string rest = trim(raw_line.substr(pos + 8));  // use original case for value parse

    size_t eq = rest.find('=');
    if (eq == std::string::npos) return false;

    std::string target     = trim(rest.substr(0, eq));
    std::string value_str  = trim(rest.substr(eq + 1));
    if (target.empty() || value_str.empty()) return false;

    // Parse numeric value
    uint64_t value = 0;
    try {
        value = std::stoull(value_str, nullptr, 0);
    } catch (...) {
        return false;
    }

    out.expected_value = value;
    out.source_file    = source_file;
    out.line_number    = lineno;

    // Parse target (compare uppercase)
    std::string up_target = target;
    std::transform(up_target.begin(), up_target.end(), up_target.begin(), ::toupper);

    if (!up_target.empty() && up_target[0] == 'R') {
        int idx = -1;
        try { idx = std::stoi(up_target.substr(1)); } catch (...) { return false; }
        if (idx < 0 || idx > 15) return false;
        out.type    = Expectation::Type::Register;
        out.reg_idx = idx;
        return true;
    }

    if (up_target.size() > 4 && up_target.substr(0, 4) == "MEM:") {
        try {
            out.type     = Expectation::Type::Memory;
            out.mem_addr = std::stoull(target.substr(4), nullptr, 0);
            return true;
        } catch (...) {
            return false;
        }
    }

    return false;
}

// ---------------------------------------------------------------------------
// ProjectFile::load
// ---------------------------------------------------------------------------

ProjectFile ProjectFile::load(const std::string& path) {
    std::ifstream f(path);
    if (!f.is_open())
        throw std::runtime_error("Cannot open project file: " + path);

    ProjectFile proj;
    proj.path = path;
    proj.dir  = dirOf(path);
    proj.name = stemOf(path);

    // Read source paths (one per line; # comments and blank lines ignored)
    std::string line;
    while (std::getline(f, line)) {
        std::string t = trim(line);
        if (t.empty() || t[0] == '#') continue;

        // Resolve relative paths against the project directory
        std::string src_path;
        if (!t.empty() && t[0] == '/') {
            src_path = t;
        } else {
            src_path = proj.dir + "/" + t;
        }
        proj.sources.push_back(src_path);
    }

    // Scan each source file for "; EXPECT" assertions
    for (const auto& src_path : proj.sources) {
        std::ifstream src(src_path);
        if (!src.is_open()) continue;
        std::string src_line;
        int lineno = 1;
        while (std::getline(src, src_line)) {
            Expectation exp{};
            if (parseExpect(src_line, src_path, lineno, exp))
                proj.expectations.push_back(exp);
            ++lineno;
        }
    }

    return proj;
}

// ---------------------------------------------------------------------------
// ProjectFile::save
// ---------------------------------------------------------------------------

void ProjectFile::save() const {
    std::ofstream f(path);
    if (!f.is_open())
        throw std::runtime_error("Cannot write project file: " + path);

    f << "# " << name << "\n";
    for (const auto& src : sources) {
        // Write path relative to the project directory if possible
        std::string rel = src;
        std::string prefix = dir + "/";
        if (src.size() > prefix.size() && src.substr(0, prefix.size()) == prefix)
            rel = src.substr(prefix.size());
        f << rel << "\n";
    }
}
