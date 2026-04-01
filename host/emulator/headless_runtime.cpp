#include "headless_runtime.hpp"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <vector>

namespace {

uint16_t read_u16(const std::vector<uint8_t>& b, size_t off) {
    if (off + 2 > b.size()) return 0;
    return (uint16_t)b[off] | ((uint16_t)b[off + 1] << 8);
}

uint32_t read_u32(const std::vector<uint8_t>& b, size_t off) {
    if (off + 4 > b.size()) return 0;
    return (uint32_t)b[off] | ((uint32_t)b[off + 1] << 8) | ((uint32_t)b[off + 2] << 16) | ((uint32_t)b[off + 3] << 24);
}

uint64_t read_u64(const std::vector<uint8_t>& b, size_t off) {
    return (uint64_t)read_u32(b, off) | ((uint64_t)read_u32(b, off + 4) << 32);
}

bool loadRelocatableElf(IEmulatorRuntime& runtime, const std::vector<uint8_t>& bytes, std::string& error) {
    if (bytes.size() < 64) {
        error = "Error: ELF file too small";
        return false;
    }

    uint64_t e_shoff = read_u64(bytes, 0x28);
    uint16_t e_shentsize = read_u16(bytes, 0x3A);
    uint16_t e_shnum = read_u16(bytes, 0x3C);
    uint16_t e_shstrndx = read_u16(bytes, 0x3E);

    if (e_shoff + e_shnum * e_shentsize > bytes.size()) {
        error = "Error: ELF section headers out of range";
        return false;
    }

    uint64_t shstr_offset = read_u64(bytes, e_shoff + e_shentsize * e_shstrndx + 0x18);
    uint64_t shstr_size = read_u64(bytes, e_shoff + e_shentsize * e_shstrndx + 0x20);
    if (shstr_offset + shstr_size > bytes.size()) {
        error = "Error: ELF string table out of range";
        return false;
    }

    std::string shstr((const char*)&bytes[shstr_offset], (size_t)shstr_size);

    uint64_t text_offset = 0, text_size = 0;
    uint64_t symtab_offset = 0, symtab_size = 0;
    uint64_t rela_offset = 0, rela_size = 0;

    for (uint16_t i = 0; i < e_shnum; ++i) {
        uint64_t sh_base = e_shoff + (uint64_t)i * e_shentsize;
        uint32_t name_off = read_u32(bytes, sh_base);
        if (name_off >= shstr_size) continue;

        std::string name(&shstr[name_off]);
        uint64_t off = read_u64(bytes, sh_base + 0x18);
        uint64_t siz = read_u64(bytes, sh_base + 0x20);

        if (off + siz > bytes.size()) {
            error = "Error: ELF section out of range";
            return false;
        }

        if (name == ".text") {
            text_offset = off;
            text_size = siz;
        }
        if (name == ".symtab") {
            symtab_offset = off;
            symtab_size = siz;
        }
        if (name == ".rela.text") {
            rela_offset = off;
            rela_size = siz;
        }
    }

    if (text_size == 0 || text_offset + text_size > bytes.size()) {
        error = "Error: ELF .text section missing or invalid";
        return false;
    }

    std::vector<uint8_t> text(bytes.begin() + (ptrdiff_t)text_offset,
                              bytes.begin() + (ptrdiff_t)(text_offset + text_size));

    struct ElfSym {
        uint64_t value;
    };
    std::vector<ElfSym> syms;

    if (symtab_offset && symtab_size) {
        size_t entries = (size_t)(symtab_size / 24);
        syms.reserve(entries);
        for (size_t i = 0; i < entries; ++i) {
            uint64_t off = symtab_offset + i * 24;
            syms.push_back(ElfSym{ .value = read_u64(bytes, off + 8) });
        }
    }

    if (rela_offset && rela_size) {
        size_t nrecs = (size_t)(rela_size / 24);
        for (size_t i = 0; i < nrecs; ++i) {
            uint64_t off = rela_offset + i * 24;
            uint64_t r_offset = read_u64(bytes, off);
            uint64_t r_info = read_u64(bytes, off + 8);
            int64_t r_addend = (int64_t)read_u64(bytes, off + 16);
            uint32_t r_sym = (uint32_t)(r_info >> 32);
            uint32_t r_type = (uint32_t)(r_info & 0xFFFFFFFF);

            uint64_t sym_value = (r_sym > 0 && r_sym <= syms.size()) ? syms[r_sym - 1].value : 0;
            uint64_t target = sym_value + (uint64_t)r_addend;

            if (r_type == 1) {
                for (int j = 0; j < 8; ++j) text[(size_t)r_offset + (size_t)j] = (uint8_t)((target >> (8 * j)) & 0xFF);
            } else if (r_type == 2) {
                for (int j = 0; j < 4; ++j) text[(size_t)r_offset + (size_t)j] = (uint8_t)((target >> (8 * j)) & 0xFF);
            } else if (r_type == 3 || r_type == 4 || r_type == 5) {
                uint16_t instr = (uint16_t)text[(size_t)r_offset] | ((uint16_t)text[(size_t)r_offset + 1] << 8);
                int64_t pc = (int64_t)r_offset;
                int64_t diff = (int64_t)target - (pc + 2);
                int64_t rel = diff / 2;
                if (r_type == 3) instr = (instr & 0xFC0F) | ((uint16_t)(rel & 0x3F) << 4);
                else if (r_type == 4) instr = (instr & 0xFC00) | ((uint16_t)(rel & 0x3FF));
                else instr = (instr & 0xE000) | ((uint16_t)(rel & 0x1FFF));
                text[(size_t)r_offset] = instr & 0xFF;
                text[(size_t)r_offset + 1] = (instr >> 8) & 0xFF;
            }
        }
    }

    if (text.size() % 2 != 0) {
        text.push_back(0);
    }
    std::vector<uint16_t> words(text.size() / 2);
    std::memcpy(words.data(), text.data(), text.size());
    runtime.loadProgram(words);
    return true;
}

} // namespace

bool loadRuntimeImageFromPath(IEmulatorRuntime& runtime, const std::string& path, std::string& error) {
    std::ifstream file(path, std::ios::binary);
    if (!file.is_open()) {
        error = "Error: cannot open '" + path + "'";
        return false;
    }

    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    if (bytes.empty()) {
        error = "Error: file is empty";
        return false;
    }

    const bool is_elf = bytes.size() >= 4 &&
                        bytes[0] == 0x7F && bytes[1] == 'E' && bytes[2] == 'L' && bytes[3] == 'F';
    if (!is_elf) {
        if (bytes.size() % 2 != 0) bytes.push_back(0);
        std::vector<uint16_t> words(bytes.size() / 2);
        std::memcpy(words.data(), bytes.data(), bytes.size());
        runtime.loadProgram(words);
        return true;
    }

    uint16_t e_type = read_u16(bytes, 0x10);
    if (e_type == 2 || e_type == 3) {
        if (!runtime.loadProgramElf(bytes)) {
            error = "Error: failed to load ELF executable";
            return false;
        }
        return true;
    }

    return loadRelocatableElf(runtime, bytes, error);
}

int runRuntimeUntilStop(IEmulatorRuntime& runtime, const HeadlessRunOptions& options, std::string& error) {
    uint64_t cycles = 0;
    while (runtime.isRunning()) {
        if (options.max_cycles > 0 && cycles >= options.max_cycles) {
            error = "Error: execution reached max cycle limit";
            return 1;
        }

        runtime.cycle();
        ++cycles;

        if (options.stream_serial_stdout) {
            std::string chunk = runtime.drainSerialTx();
            if (!chunk.empty()) {
                std::cout << chunk << std::flush;
            }
        }
    }

    if (options.stream_serial_stdout) {
        std::string final_chunk = runtime.drainSerialTx();
        if (!final_chunk.empty()) {
            std::cout << final_chunk << std::flush;
        }
    }

    return 0;
}
