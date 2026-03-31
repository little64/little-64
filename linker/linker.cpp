#include "linker.hpp"
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <cstring>
#include <map>
#include <array>

#if defined(_WIN32)
#include <io.h>
#define access _access
#define F_OK 0
#define X_OK 1
#else
#include <unistd.h>
#endif

static uint16_t read_u16(const std::vector<uint8_t>& b, size_t off) {
    return (uint16_t)b[off] | ((uint16_t)b[off + 1] << 8);
}

static uint32_t read_u32(const std::vector<uint8_t>& b, size_t off) {
    return (uint32_t)b[off] | ((uint32_t)b[off + 1] << 8) |
           ((uint32_t)b[off + 2] << 16) | ((uint32_t)b[off + 3] << 24);
}

static uint64_t read_u64(const std::vector<uint8_t>& b, size_t off) {
    return (uint64_t)read_u32(b, off) | ((uint64_t)read_u32(b, off + 4) << 32);
}

static std::string getLldPath() {
    const char* env = std::getenv("LITTLE64_LD");
    if (env && env[0]) return env;

    const std::vector<std::string> candidates = {
        "compilers/bin/ld.lld",
        "compilers/bin/lld",
        "ld.lld",
        "lld"
    };
    for (auto const& c : candidates) {
        std::filesystem::path p(c);
        if (std::filesystem::exists(p) && access(p.c_str(), X_OK) == 0)
            return c;
        auto p2 = std::filesystem::current_path() / c;
        if (std::filesystem::exists(p2) && access(p2.c_str(), X_OK) == 0)
            return p2.string();
    }

    return {};
}

static std::optional<std::vector<uint16_t>> linkObjectsInternal(const std::vector<std::vector<uint8_t>>& objects, LinkError* err);
static std::optional<std::vector<uint8_t>> linkObjectsWithLldElf(const std::vector<std::vector<uint8_t>>& objects, LinkError* err);
static std::optional<std::vector<uint16_t>> linkObjectsWithLld(const std::vector<std::vector<uint8_t>>& objects,
                                                                 LinkError* err) {
    if (objects.empty()) {
        if (err) err->message = "No input objects";
        return std::nullopt;
    }

    std::vector<std::filesystem::path> tmp_objs;
    tmp_objs.reserve(objects.size());

    std::string pid = std::to_string(static_cast<int>(getpid()));
    for (size_t i = 0; i < objects.size(); ++i) {
        std::filesystem::path obj_path = std::filesystem::temp_directory_path() /
            ("little64_lld_obj_" + pid + "_" + std::to_string(i) + ".o");
        std::ofstream f(obj_path, std::ios::binary);
        if (!f.is_open()) {
            if (err) err->message = "Failed to create temp object file: " + obj_path.string();
            return std::nullopt;
        }
        f.write(reinterpret_cast<const char*>(objects[i].data()), objects[i].size());
        f.close();
        tmp_objs.push_back(obj_path);
    }

    std::filesystem::path out_path = std::filesystem::temp_directory_path() /
        ("little64_lld_out_" + pid + ".bin");

    std::string lld = getLldPath();
    if (lld.empty()) {
        if (err) err->message = "No ld.lld linker found. Set LITTLE64_LD to a valid linker.";
        return std::nullopt;
    }

    // Generate a temporary linker script to enforce the same section ordering used
    // by the legacy linkObjectsInternal pipeline.
    std::filesystem::path script_path = std::filesystem::temp_directory_path() /
        ("little64_lld_script_" + pid + ".ld");
    std::ofstream script_file(script_path);
    if (!script_file.is_open()) {
        if (err) err->message = "Failed to create ld.lld script file: " + script_path.string();
        for (auto const& obj : tmp_objs) std::filesystem::remove(obj);
        return std::nullopt;
    }
    script_file << "SECTIONS\n";
    script_file << "{\n";
    script_file << "  .text 0x0 : { *(.text*) }\n";
    script_file << "  .rodata : { *(.rodata*) }\n";
    script_file << "  .data : { *(.data*) }\n";
    script_file << "  .bss : { *(.bss*) }\n";
    script_file << "  /DISCARD/ : { *(.comment) *(.note.*) *(.debug*) *(.eh_frame*) *(.llvm*) }\n";
    script_file << "}\n";
    script_file.close();

    std::ostringstream cmd;
    cmd << '"' << lld << '"' << " -T " << '"' << script_path.string() << '"'
        << " --oformat=binary -o " << '"' << out_path.string() << '"';
    for (auto const& obj : tmp_objs) {
        cmd << ' ' << '"' << obj.string() << '"';
    }
    cmd << " 2>&1";

    std::array<char, 512> buf;
    std::string output;
    FILE* pipe = popen(cmd.str().c_str(), "r");
    if (!pipe) {
        if (err) err->message = "Failed to run ld.lld";
        return std::nullopt;
    }
    while (fgets(buf.data(), static_cast<int>(buf.size()), pipe) != nullptr) {
        output += buf.data();
    }
    int status = pclose(pipe);

    for (auto const& obj : tmp_objs) {
        std::filesystem::remove(obj);
    }

    if (status != 0) {
        if (err) {
            std::ostringstream se;
            se << "ld.lld failed with status " << status << ".\n" << output;
            err->message = se.str();
        }
        std::filesystem::remove(out_path);
        std::filesystem::remove(script_path);
        return std::nullopt;
    }

    std::ifstream f(out_path, std::ios::binary);
    if (!f.is_open()) {
        if (err) err->message = "ld.lld succeeded but cannot open output file";
        std::filesystem::remove(out_path);
        std::filesystem::remove(script_path);
        return std::nullopt;
    }
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    f.close();
    std::filesystem::remove(out_path);
    std::filesystem::remove(script_path);

    if (bytes.empty()) {
        if (err) err->message = "ld.lld output is empty";
        return std::nullopt;
    }

    if (bytes.size() % 2 != 0) bytes.push_back(0);
    std::vector<uint16_t> outv(bytes.size() / 2);
    for (size_t i = 0; i < outv.size(); ++i) {
        outv[i] = (uint16_t)bytes[2*i] | ((uint16_t)bytes[2*i+1] << 8);
    }

    if (err) {
        LinkError internal_err;
        auto internal = linkObjectsInternal(objects, &internal_err);
        err->entry_address = internal_err.entry_address;
        err->has_entry = internal_err.has_entry;
        err->message.clear();
    }

    return outv;
}

static std::optional<std::vector<uint8_t>> linkObjectsWithLldElf(const std::vector<std::vector<uint8_t>>& objects,
                                                                   LinkError* err) {
    if (objects.empty()) {
        if (err) err->message = "No input objects";
        return std::nullopt;
    }

    std::vector<std::filesystem::path> tmp_objs;
    tmp_objs.reserve(objects.size());

    std::string pid = std::to_string(static_cast<int>(getpid()));
    for (size_t i = 0; i < objects.size(); ++i) {
        std::filesystem::path obj_path = std::filesystem::temp_directory_path() /
            ("little64_lld_obj_" + pid + "_" + std::to_string(i) + ".o");
        std::ofstream f(obj_path, std::ios::binary);
        if (!f.is_open()) {
            if (err) err->message = "Failed to create temp object file: " + obj_path.string();
            return std::nullopt;
        }
        f.write(reinterpret_cast<const char*>(objects[i].data()), objects[i].size());
        f.close();
        tmp_objs.push_back(obj_path);
    }

    std::filesystem::path out_path = std::filesystem::temp_directory_path() /
        ("little64_lld_out_" + pid + ".elf");

    std::string lld = getLldPath();
    if (lld.empty()) {
        if (err) err->message = "No ld.lld linker found. Set LITTLE64_LD to a valid linker.";
        return std::nullopt;
    }

    std::filesystem::path script_path = std::filesystem::temp_directory_path() /
        ("little64_lld_script_" + pid + ".ld");
    std::ofstream script_file(script_path);
    if (!script_file.is_open()) {
        if (err) err->message = "Failed to create ld.lld script file: " + script_path.string();
        for (auto const& obj : tmp_objs) std::filesystem::remove(obj);
        return std::nullopt;
    }
    script_file << "SECTIONS\n";
    script_file << "{\n";
    script_file << "  .text 0x0 : { *(.text*) }\n";
    script_file << "  .rodata : { *(.rodata*) }\n";
    script_file << "  .data : { *(.data*) }\n";
    script_file << "  .bss : { *(.bss*) }\n";
    script_file << "  /DISCARD/ : { *(.comment) *(.note.*) *(.debug*) *(.eh_frame*) *(.llvm*) }\n";
    script_file << "}\n";
    script_file.close();

    std::ostringstream cmd;
    cmd << '"' << lld << '"' << " -T " << '"' << script_path.string() << '"'
        << " -o " << '"' << out_path.string() << '"';
    for (auto const& obj : tmp_objs) {
        cmd << ' ' << '"' << obj.string() << '"';
    }
    cmd << " 2>&1";

    std::array<char, 512> buf;
    std::string output;
    FILE* pipe = popen(cmd.str().c_str(), "r");
    if (!pipe) {
        if (err) err->message = "Failed to run ld.lld";
        return std::nullopt;
    }
    while (fgets(buf.data(), static_cast<int>(buf.size()), pipe) != nullptr) {
        output += buf.data();
    }
    int status = pclose(pipe);

    for (auto const& obj : tmp_objs) {
        std::filesystem::remove(obj);
    }

    if (status != 0) {
        if (err) {
            std::ostringstream se;
            se << "ld.lld failed with status " << status << ".\n" << output;
            err->message = se.str();
        }
        std::filesystem::remove(out_path);
        std::filesystem::remove(script_path);
        return std::nullopt;
    }

    std::ifstream f(out_path, std::ios::binary);
    if (!f.is_open()) {
        if (err) err->message = "ld.lld succeeded but cannot open output file";
        std::filesystem::remove(out_path);
        std::filesystem::remove(script_path);
        return std::nullopt;
    }
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    f.close();

    std::filesystem::remove(out_path);
    std::filesystem::remove(script_path);

    if (bytes.empty()) {
        if (err) err->message = "ld.lld output is empty";
        return std::nullopt;
    }

    return bytes;
}

std::optional<std::vector<uint16_t>> Linker::linkObjects(const std::vector<std::vector<uint8_t>>& objects, LinkError* err) {
    // Prefer lld+binary output for final linker, while retaining the old internal
    // pinball linker as a fallback for compatibility.
    auto linked = linkObjectsWithLld(objects, err);
    if (linked) {
        return linked;
    }

    const char* fallbackEnv = std::getenv("LITTLE64_USE_INTERNAL_LINKER");
    if (!fallbackEnv || fallbackEnv[0] == '\0' || fallbackEnv[0] == '1') {
        return linkObjectsInternal(objects, err);
    }

    return std::nullopt;
}

std::optional<std::vector<uint8_t>> Linker::linkObjectsElf(const std::vector<std::vector<uint8_t>>& objects, LinkError* err) {
    // Prefer lld+ELF output for program loading.
    auto elf_blob = linkObjectsWithLldElf(objects, err);
    if (elf_blob) {
        return elf_blob;
    }

    // Fall back to internal linker output via an in-memory ELF create path.
    // The internal linker currently produces flattened words, so we are not
    // supporting fallback creation of full ELF here.
    if (err && err->message.empty())
        err->message = "ld.lld ELF link failed and no fallback available";
    return std::nullopt;
}

// ELF relocation type numbers for Little64 (from ELFRelocs/Little64.def)
// 0 = R_LITTLE64_NONE
// 1 = R_LITTLE64_ABS64   — 64-bit absolute address
// 2 = R_LITTLE64_ABS32   — 32-bit absolute address
// 3 = R_LITTLE64_PCREL6  — 6-bit PC-relative, field [9:4]
// 4 = R_LITTLE64_PCREL10 — 10-bit PC-relative, field [9:0]
static constexpr uint32_t R_ABS64   = 1;
static constexpr uint32_t R_ABS32   = 2;
static constexpr uint32_t R_PCREL6  = 3;
static constexpr uint32_t R_PCREL10 = 4;

static std::optional<std::vector<uint16_t>> linkObjectsInternal(const std::vector<std::vector<uint8_t>>& objects, LinkError* err) {
    struct SectionInfo { uint64_t offset; uint64_t size; };
    struct Reloc { uint64_t offset; uint32_t sym; uint32_t type; int64_t addend; };

    // A deferred .rela.rodata* entry: we store the raw reloc-within-section offset
    // and the sh_info (target section shndx) separately, because the corresponding
    // .rodata.* section may not have been scanned yet when we encounter the .rela.
    struct DeferredRodataRela {
        uint32_t target_shndx; // sh_info of the .rela.rodata* section
        std::vector<Reloc> relocs; // offsets are relative to the target section
    };

    struct ObjectContext {
        SectionInfo text;
        SectionInfo data;
        uint64_t bss_size = 0;

        std::vector<uint8_t> text_bytes;
        std::vector<uint8_t> data_bytes;

        // All .rodata* sections are concatenated into one blob.
        // rodata_sec_offsets maps shndx → byte offset within rodata_bytes.
        std::vector<uint8_t> rodata_bytes;
        std::map<uint32_t, uint64_t> rodata_sec_offsets;

        std::vector<Reloc> text_relocs;
        std::vector<Reloc> data_relocs;
        std::vector<Reloc> rodata_relocs; // offsets are within rodata_bytes

        std::vector<DeferredRodataRela> deferred_rodata_relas;

        int text_shndx = -1;
        int data_shndx = -1;
        int bss_shndx  = -1;

        struct SymEntry { std::string name; uint8_t info; uint16_t shndx; uint64_t value; };
        std::map<uint32_t, SymEntry> syms; // ELF 1-based symbol index -> entry
    };

    std::vector<ObjectContext> objs;
    for (const auto& file : objects) {
        if (file.size() < 64) {
            if (err) err->message = "Object file too small";
            return std::nullopt;
        }
        if (!(file[0] == 0x7F && file[1] == 'E' && file[2] == 'L' && file[3] == 'F')) {
            if (err) err->message = "Not an ELF file";
            return std::nullopt;
        }
        if (file[4] != 2 || file[5] != 1) { // ELF64 little
            if (err) err->message = "Only ELF64 little endian is supported";
            return std::nullopt;
        }
        uint64_t e_shoff = read_u64(file, 0x28);
        uint16_t e_shentsize = read_u16(file, 0x3A);
        uint16_t e_shnum = read_u16(file, 0x3C);
        uint16_t e_shstrndx = read_u16(file, 0x3E);
        if (e_shoff + (uint64_t)e_shnum * e_shentsize > file.size()) {
            if (err) err->message = "ELF section header out of range";
            return std::nullopt;
        }
        if (e_shstrndx >= e_shnum) {
            if (err) err->message = "e_shstrndx out of range";
            return std::nullopt;
        }

        uint64_t shstr_offset = read_u64(file, e_shoff + (uint64_t)e_shstrndx * e_shentsize + 0x18);
        uint64_t shstr_size   = read_u64(file, e_shoff + (uint64_t)e_shstrndx * e_shentsize + 0x20);
        if (shstr_offset + shstr_size > file.size()) {
            if (err) err->message = ".shstrtab out of range";
            return std::nullopt;
        }

        std::string shstr((const char*)&file[shstr_offset], (size_t)shstr_size);

        ObjectContext ctx{};
        uint64_t symtab_offset=0, symtab_size=0, symtab_entsize=0;
        uint64_t strtab_offset=0, strtab_size=0;

        for (uint16_t si = 0; si < e_shnum; ++si) {
            uint64_t sh_base = e_shoff + (uint64_t)si * e_shentsize;
            uint32_t name = read_u32(file, sh_base);
            if (name >= shstr_size) continue;
            const char* namep = shstr.c_str() + name;
            uint64_t off     = read_u64(file, sh_base + 0x18);
            uint64_t sz      = read_u64(file, sh_base + 0x20);
            uint64_t entsize = read_u64(file, sh_base + 0x38);

            if (strcmp(namep, ".text") == 0) {
                if (off + sz > file.size()) { if (err) err->message = ".text out of range"; return std::nullopt; }
                ctx.text_shndx = si;
                ctx.text.offset = off;
                ctx.text.size = sz;
                ctx.text_bytes.assign(file.begin() + off, file.begin() + off + sz);
            } else if (strcmp(namep, ".data") == 0) {
                if (off + sz > file.size()) { if (err) err->message = ".data out of range"; return std::nullopt; }
                ctx.data_shndx = si;
                ctx.data.offset = off;
                ctx.data.size = sz;
                ctx.data_bytes.assign(file.begin() + off, file.begin() + off + sz);
            } else if (strcmp(namep, ".bss") == 0) {
                ctx.bss_shndx = si;
                ctx.bss_size = sz;
            } else if (strncmp(namep, ".rodata", 7) == 0 && (namep[7] == '\0' || namep[7] == '.')) {
                // .rodata or .rodata.something (e.g. .rodata.cst8, .rodata.str1.1)
                if (sz == 0) continue; // skip empty sections
                if (off + sz > file.size()) { if (err) err->message = ".rodata out of range"; return std::nullopt; }
                ctx.rodata_sec_offsets[si] = ctx.rodata_bytes.size();
                ctx.rodata_bytes.insert(ctx.rodata_bytes.end(),
                                        file.begin() + off, file.begin() + off + sz);
            } else if (strcmp(namep, ".symtab") == 0) {
                symtab_offset = off;
                symtab_size = sz;
                symtab_entsize = entsize;
            } else if (strcmp(namep, ".strtab") == 0) {
                if (off + sz > file.size()) { if (err) err->message = ".strtab out of range"; return std::nullopt; }
                strtab_offset = off;
                strtab_size = sz;
            } else if (strcmp(namep, ".rela.text") == 0) {
                if (off + sz > file.size()) { if (err) err->message = ".rela.text out of range"; return std::nullopt; }
                for (uint64_t ri = 0; ri + 24 <= sz; ri += 24) {
                    uint64_t roff  = read_u64(file, off + ri);
                    uint64_t rinfo = read_u64(file, off + ri + 8);
                    int64_t  radd  = (int64_t)read_u64(file, off + ri + 16);
                    ctx.text_relocs.push_back({ roff, (uint32_t)(rinfo >> 32), (uint32_t)(rinfo & 0xFFFFFFFF), radd });
                }
            } else if (strcmp(namep, ".rela.data") == 0) {
                if (off + sz > file.size()) { if (err) err->message = ".rela.data out of range"; return std::nullopt; }
                for (uint64_t ri = 0; ri + 24 <= sz; ri += 24) {
                    uint64_t roff  = read_u64(file, off + ri);
                    uint64_t rinfo = read_u64(file, off + ri + 8);
                    int64_t  radd  = (int64_t)read_u64(file, off + ri + 16);
                    ctx.data_relocs.push_back({ roff, (uint32_t)(rinfo >> 32), (uint32_t)(rinfo & 0xFFFFFFFF), radd });
                }
            } else if (strncmp(namep, ".rela.rodata", 12) == 0) {
                // .rela.rodata or .rela.rodata.something
                if (off + sz > file.size()) { if (err) err->message = ".rela.rodata out of range"; return std::nullopt; }
                // sh_info tells us which section these relocations apply to
                uint32_t target_shndx = read_u32(file, sh_base + 0x2C);
                DeferredRodataRela dr;
                dr.target_shndx = target_shndx;
                for (uint64_t ri = 0; ri + 24 <= sz; ri += 24) {
                    uint64_t roff  = read_u64(file, off + ri);
                    uint64_t rinfo = read_u64(file, off + ri + 8);
                    int64_t  radd  = (int64_t)read_u64(file, off + ri + 16);
                    dr.relocs.push_back({ roff, (uint32_t)(rinfo >> 32), (uint32_t)(rinfo & 0xFFFFFFFF), radd });
                }
                ctx.deferred_rodata_relas.push_back(std::move(dr));
            }
        }

        // Resolve deferred .rela.rodata* entries now that all sections are known.
        for (auto& dr : ctx.deferred_rodata_relas) {
            auto sec_it = ctx.rodata_sec_offsets.find(dr.target_shndx);
            uint64_t base_in_blob = (sec_it != ctx.rodata_sec_offsets.end()) ? sec_it->second : 0;
            for (auto& r : dr.relocs) {
                ctx.rodata_relocs.push_back({ base_in_blob + r.offset, r.sym, r.type, r.addend });
            }
        }

        if (symtab_offset && symtab_size && symtab_entsize == 24 && strtab_offset && strtab_size) {
            uint64_t entries = symtab_size / symtab_entsize;
            for (uint64_t i = 1; i < entries; ++i) { // skip null entry at index 0
                uint64_t sym_off = symtab_offset + i * symtab_entsize;
                if (sym_off + symtab_entsize > file.size()) break;
                uint32_t name_idx = read_u32(file, sym_off);
                uint8_t  info     = file[sym_off + 4];
                uint16_t shndx    = read_u16(file, sym_off + 6);
                uint64_t value    = read_u64(file, sym_off + 8);

                std::string sym_name;
                if (name_idx < strtab_size) {
                    const char* ptr = (const char*)&file[strtab_offset + name_idx];
                    size_t max_len  = strtab_size - name_idx;
                    sym_name.assign(ptr, strnlen(ptr, max_len));
                }
                ctx.syms[static_cast<uint32_t>(i)] = { sym_name, info, shndx, value };
            }
        }

        objs.push_back(std::move(ctx));
    }

    // Assign section base addresses for each object, respecting 2-byte alignment.
    // Layout per object: .text → .rodata → .data → .bss
    struct ObjLayout {
        uint64_t text_base;
        uint64_t rodata_base;
        uint64_t data_base;
        uint64_t bss_base;
        uint64_t end;
    };
    std::vector<ObjLayout> layouts;
    layouts.reserve(objs.size());

    uint64_t next_address = 0;
    for (const auto& ctx : objs) {
        if (next_address % 2 != 0) next_address++;
        uint64_t text_base = next_address;
        next_address += ctx.text.size;

        if (next_address % 2 != 0) next_address++;
        uint64_t rodata_base = next_address;
        next_address += ctx.rodata_bytes.size();

        if (next_address % 2 != 0) next_address++;
        uint64_t data_base = next_address;
        next_address += ctx.data.size;

        if (next_address % 2 != 0) next_address++;
        uint64_t bss_base = next_address;
        next_address += ctx.bss_size;

        layouts.push_back({ text_base, rodata_base, data_base, bss_base, next_address });
    }

    // Build global symbol table: name -> absolute address.
    std::map<std::string, uint64_t> global_symbols;
    for (size_t i = 0; i < objs.size(); ++i) {
        const auto& ctx = objs[i];
        const auto& lay = layouts[i];
        for (const auto& [idx, s] : ctx.syms) {
            if (s.shndx == 0 || s.name.empty()) continue;
            uint64_t abs_addr = 0;
            if (s.shndx == ctx.text_shndx) {
                abs_addr = lay.text_base + s.value;
            } else if (s.shndx == ctx.data_shndx) {
                abs_addr = lay.data_base + s.value;
            } else if (s.shndx == ctx.bss_shndx) {
                abs_addr = lay.bss_base + s.value;
            } else {
                // Check if this symbol is in a .rodata* section
                auto rod_it = ctx.rodata_sec_offsets.find(s.shndx);
                if (rod_it != ctx.rodata_sec_offsets.end()) {
                    abs_addr = lay.rodata_base + rod_it->second + s.value;
                } else {
                    // Unsupported section — skip
                    continue;
                }
            }
            global_symbols[s.name] = abs_addr;
        }
    }

    // Determine link entry point from _start symbol if available.
    if (err) {
        auto it = global_symbols.find("_start");
        if (it != global_symbols.end()) {
            err->entry_address = it->second;
            err->has_entry = true;
        } else {
            err->entry_address = 0;
            err->has_entry = false;
        }
    }

    // Concatenate all sections and apply relocations.
    std::vector<uint8_t> linked_text;

    for (size_t i = 0; i < objs.size(); ++i) {
        auto& ctx = objs[i];
        const auto& lay = layouts[i];

        // apply_reloc patches linked_text at (section_base + rel.offset).
        // section_bytes is used only to bounds-check rel.offset.
        // PC-relative formula: rel_val = (sym_addr + addend - (patch_addr + 2)) / 2
        // This matches the CPU which post-increments PC by 2 before applying the offset.
        auto apply_reloc = [&](uint64_t section_base,
                               const std::vector<uint8_t>& section_bytes,
                               const Reloc& rel) -> bool {
            uint64_t needed = 0;
            if      (rel.type == R_ABS64)   needed = 8;
            else if (rel.type == R_ABS32)   needed = 4;
            else if (rel.type == R_PCREL6)  needed = 2;
            else if (rel.type == R_PCREL10) needed = 2;
            else return false; // unknown relocation type — skip silently

            if (rel.offset + needed > section_bytes.size()) {
                if (err) err->message = "Relocation offset out of section range";
                return false;
            }

            auto sym_it = ctx.syms.find(rel.sym);
            if (rel.sym == 0 || sym_it == ctx.syms.end()) {
                if (err) err->message = "Invalid symbol index in relocation";
                return false;
            }

            const std::string& sym_name = sym_it->second.name;
            auto gs_it = global_symbols.find(sym_name);
            if (gs_it == global_symbols.end()) {
                if (err) err->message = "Undefined symbol in relocation: " + sym_name;
                return false;
            }

            uint64_t sym_addr  = gs_it->second;
            uint64_t patch_addr = section_base + rel.offset;

            if (rel.type == R_ABS64) {
                if (patch_addr + 8 > linked_text.size()) { if (err) err->message = "ABS64 patch out of range"; return false; }
                uint64_t value = sym_addr + (uint64_t)(int64_t)rel.addend;
                for (int j = 0; j < 8; j++)
                    linked_text[patch_addr + j] = (uint8_t)((value >> (8*j)) & 0xFF);
            } else if (rel.type == R_ABS32) {
                if (patch_addr + 4 > linked_text.size()) { if (err) err->message = "ABS32 patch out of range"; return false; }
                uint32_t value = (uint32_t)(sym_addr + (uint64_t)(int64_t)rel.addend);
                for (int j = 0; j < 4; j++)
                    linked_text[patch_addr + j] = (uint8_t)((value >> (8*j)) & 0xFF);
            } else if (rel.type == R_PCREL6) {
                if (patch_addr + 2 > linked_text.size()) { if (err) err->message = "PCREL6 patch out of range"; return false; }
                uint16_t instr = (uint16_t)linked_text[patch_addr] | ((uint16_t)linked_text[patch_addr+1] << 8);
                int64_t target  = (int64_t)sym_addr + rel.addend;
                int64_t diff    = target - ((int64_t)patch_addr + 2);
                if (diff % 2 != 0) { if (err) err->message = "PCREL6 target not instruction aligned"; return false; }
                int64_t rel_val = diff / 2;
                if (rel_val < -32 || rel_val > 31) { if (err) err->message = "PCREL6 reloc out of range"; return false; }
                uint16_t new_instr = (instr & 0xFC0F) | ((uint16_t)(rel_val & 0x3F) << 4);
                linked_text[patch_addr]   = new_instr & 0xFF;
                linked_text[patch_addr+1] = (new_instr >> 8) & 0xFF;
            } else { // R_PCREL10
                if (patch_addr + 2 > linked_text.size()) { if (err) err->message = "PCREL10 patch out of range"; return false; }
                uint16_t instr = (uint16_t)linked_text[patch_addr] | ((uint16_t)linked_text[patch_addr+1] << 8);
                // Verify this is actually a JUMP instruction (format 01, opcode 11-15)
                uint8_t fmt = (instr >> 14) & 0x3;
                uint8_t op  = (instr >> 10) & 0xF;
                if (fmt != 1 || op < 11) {
                    if (err) err->message = "R_PCREL10 applied to non-JUMP instruction";
                    return false;
                }
                int64_t target  = (int64_t)sym_addr + rel.addend;
                int64_t diff    = target - ((int64_t)patch_addr + 2);
                if (diff % 2 != 0) { if (err) err->message = "PCREL10 target not instruction aligned"; return false; }
                int64_t rel_val = diff / 2;
                if (rel_val < -512 || rel_val > 511) { if (err) err->message = "PCREL10 reloc out of range"; return false; }
                uint16_t new_instr = (instr & 0xFC00) | ((uint16_t)(rel_val & 0x3FF));
                linked_text[patch_addr]   = new_instr & 0xFF;
                linked_text[patch_addr+1] = (new_instr >> 8) & 0xFF;
            }
            return true;
        };

        // --- Append .text ---
        while (linked_text.size() % 2 != 0) linked_text.push_back(0);
        if (linked_text.size() > lay.text_base) {
            if (err) err->message = "Linker internal state mismatch";
            return std::nullopt;
        }
        while (linked_text.size() < lay.text_base) linked_text.push_back(0);
        linked_text.insert(linked_text.end(), ctx.text_bytes.begin(), ctx.text_bytes.end());

        for (auto& r : ctx.text_relocs) {
            if (!apply_reloc(lay.text_base, ctx.text_bytes, r)) return std::nullopt;
        }

        // --- Append .rodata ---
        if (!ctx.rodata_bytes.empty()) {
            while (linked_text.size() % 2 != 0) linked_text.push_back(0);
            while (linked_text.size() < lay.rodata_base) linked_text.push_back(0);
            linked_text.insert(linked_text.end(), ctx.rodata_bytes.begin(), ctx.rodata_bytes.end());

            for (auto& r : ctx.rodata_relocs) {
                if (!apply_reloc(lay.rodata_base, ctx.rodata_bytes, r)) return std::nullopt;
            }
        }

        // --- Append .data ---
        if (linked_text.size() < lay.data_base)
            while (linked_text.size() < lay.data_base) linked_text.push_back(0);
        linked_text.insert(linked_text.end(), ctx.data_bytes.begin(), ctx.data_bytes.end());

        for (auto& r : ctx.data_relocs) {
            if (!apply_reloc(lay.data_base, ctx.data_bytes, r)) return std::nullopt;
        }

        // --- Append .bss (zero-initialised) ---
        if (linked_text.size() < lay.bss_base)
            while (linked_text.size() < lay.bss_base) linked_text.push_back(0);
        linked_text.insert(linked_text.end(), ctx.bss_size, 0);
    }

    if (linked_text.size() % 2 != 0) linked_text.push_back(0);
    std::vector<uint16_t> outv(linked_text.size() / 2);
    for (size_t i = 0; i < outv.size(); ++i) {
        outv[i] = (uint16_t)linked_text[2*i] | ((uint16_t)linked_text[2*i+1] << 8);
    }
    return outv;
}
