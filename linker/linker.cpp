#include "linker.hpp"
#include <cstring>
#include <map>

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

std::optional<std::vector<uint16_t>> Linker::linkObjects(const std::vector<std::vector<uint8_t>>& objects, LinkError* err) {
    struct SectionInfo { uint64_t offset; uint64_t size; };
    struct Reloc { uint64_t offset; uint32_t sym; uint32_t type; int64_t addend; };

    struct ObjectContext {
        SectionInfo text;
        std::vector<uint8_t> text_bytes;
        std::vector<Reloc> relocs;
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
        uint64_t shstr_size = read_u64(file, e_shoff + (uint64_t)e_shstrndx * e_shentsize + 0x20);
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
            uint64_t off = read_u64(file, sh_base + 0x18);
            uint64_t sz = read_u64(file, sh_base + 0x20);
            uint64_t entsize = read_u64(file, sh_base + 0x38);

            if (strcmp(namep, ".text") == 0) {
                if (off + sz > file.size()) { if (err) err->message = ".text out of range"; return std::nullopt; }
                ctx.text.offset = off;
                ctx.text.size = sz;
                ctx.text_bytes.assign(file.begin() + off, file.begin() + off + sz);
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
                    uint64_t roff = read_u64(file, off + ri);
                    uint64_t rinfo = read_u64(file, off + ri + 8);
                    int64_t radd = (int64_t)read_u64(file, off + ri + 16);
                    ctx.relocs.push_back({ roff, (uint32_t)(rinfo >> 32), (uint32_t)(rinfo & 0xFFFFFFFF), radd });
                }
            }
        }

        if (symtab_offset && symtab_size && symtab_entsize == 24 && strtab_offset && strtab_size) {
            uint64_t entries = symtab_size / symtab_entsize;
            for (uint64_t i = 1; i < entries; ++i) { // skip null entry at index 0
                uint64_t sym_off = symtab_offset + i * symtab_entsize;
                if (sym_off + symtab_entsize > file.size()) break;
                uint32_t name_idx = read_u32(file, sym_off);
                uint8_t info = file[sym_off + 4];
                uint16_t shndx = read_u16(file, sym_off + 6);
                uint64_t value = read_u64(file, sym_off + 8);

                std::string sym_name;
                if (name_idx < strtab_size) {
                    const char* ptr = (const char*)&file[strtab_offset + name_idx];
                    size_t max_len = strtab_size - name_idx;
                    sym_name.assign(ptr, strnlen(ptr, max_len));
                }
                ctx.syms[static_cast<uint32_t>(i)] = { sym_name, info, shndx, value };
            }
        }

        objs.push_back(std::move(ctx));
    }

    // Build global symbol table: name -> absolute address.
    // Track offsets with the same 2-byte alignment logic used when concatenating.
    std::map<std::string, uint64_t> global_symbols;
    uint64_t cur_offset = 0;
    for (const auto& ctx : objs) {
        if (cur_offset % 2 != 0) cur_offset++;
        for (const auto& [idx, s] : ctx.syms) {
            if (s.shndx != 0 && !s.name.empty())
                global_symbols[s.name] = cur_offset + s.value;
        }
        cur_offset += ctx.text.size;
    }

    // Concatenate .text sections and apply relocations.
    std::vector<uint8_t> linked_text;

    for (auto& ctx : objs) {
        // Ensure 16-bit alignment before each object.
        while (linked_text.size() % 2 != 0) linked_text.push_back(0);
        uint64_t obj_text_base = linked_text.size();

        linked_text.insert(linked_text.end(), ctx.text_bytes.begin(), ctx.text_bytes.end());

        for (auto& r : ctx.relocs) {
            uint64_t needed = 0;
            if (r.type == 1) {
                needed = 2;
            } else if (r.type == 2) {
                needed = 8;
            } else {
                if (err) err->message = "Unsupported relocation type";
                return std::nullopt;
            }
            if (r.offset + needed > ctx.text_bytes.size()) {
                if (err) err->message = "Relocation offset out of .text range";
                return std::nullopt;
            }
            auto sym_it = ctx.syms.find(r.sym);
            if (r.sym == 0 || sym_it == ctx.syms.end()) {
                if (err) err->message = "Invalid symbol index in relocation";
                return std::nullopt;
            }
            const std::string& sym_name = sym_it->second.name;
            auto gs_it = global_symbols.find(sym_name);
            if (gs_it == global_symbols.end()) {
                if (err) err->message = "Undefined symbol in relocation: " + sym_name;
                return std::nullopt;
            }
            uint64_t sym_addr = gs_it->second;
            uint64_t patch_addr = obj_text_base + r.offset;
            if (r.type == 1) {
                // PCREL6: patch the 6-bit signed PC-relative offset field in a LS_PCREL instruction.
                if (patch_addr + 2 > linked_text.size()) {
                    if (err) err->message = "PCREL patch out of range";
                    return std::nullopt;
                }
                uint16_t instr = (uint16_t)linked_text[patch_addr] | ((uint16_t)linked_text[patch_addr+1] << 8);
                int64_t target = (int64_t)sym_addr + r.addend;
                int64_t diff = target - ((int64_t)patch_addr + 2);
                if (diff % 2 != 0) {
                    if (err) err->message = "PCREL target not instruction aligned";
                    return std::nullopt;
                }
                int64_t rel = diff / 2;
                if (rel < -32 || rel > 31) {
                    if (err) err->message = "PCREL reloc out of range";
                    return std::nullopt;
                }
                // Mask 0xFC0F keeps bits [15:10] (format + full 4-bit opcode) and [3:0] (Rd),
                // clearing only bits [9:4] which hold the 6-bit PC-relative offset field.
                // 0xF00F would incorrectly zero opcode bits [11:10], corrupting all opcodes
                // whose lower two bits are non-zero (STORE, PUSH, POP, JUMP.Z, JUMP.S, etc.).
                uint16_t new_instr = (instr & 0xFC0F) | ((uint16_t)(rel & 0x3F) << 4);
                linked_text[patch_addr] = new_instr & 0xFF;
                linked_text[patch_addr+1] = (new_instr >> 8) & 0xFF;
            } else {
                // ABS64: write absolute 64-bit address.
                if (patch_addr + 8 > linked_text.size()) {
                    if (err) err->message = "ABS64 patch out of range";
                    return std::nullopt;
                }
                uint64_t value = sym_addr + r.addend;
                for (int j = 0; j < 8; j++) {
                    linked_text[patch_addr + j] = (uint8_t)((value >> (8*j)) & 0xFF);
                }
            }
        }
    }

    if (linked_text.size() % 2 != 0) linked_text.push_back(0);
    std::vector<uint16_t> outv(linked_text.size() / 2);
    for (size_t i = 0; i < outv.size(); ++i) {
        outv[i] = (uint16_t)linked_text[2*i] | ((uint16_t)linked_text[2*i+1] << 8);
    }
    return outv;
}
