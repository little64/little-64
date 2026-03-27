#include "cpu.hpp"
#include "serial_device.hpp"
#include <iostream>
#include <fstream>
#include <vector>
#include <cstdint>
#include <cstring>
#include <string>
#include <algorithm>

static void printUsage(const char* argv0) {
    std::cerr << "Usage: " << argv0 << " <binary.bin|object.o>\n"
              << "  Runs the assembled binary/ELF object and prints any serial (UART) output to stdout.\n";
}

static uint16_t read_u16(const std::vector<uint8_t>& b, size_t off) {
    return (uint16_t)b[off] | ((uint16_t)b[off+1] << 8);
}

static uint32_t read_u32(const std::vector<uint8_t>& b, size_t off) {
    return (uint32_t)b[off] | ((uint32_t)b[off+1] << 8) | ((uint32_t)b[off+2] << 16) | ((uint32_t)b[off+3] << 24);
}

static uint64_t read_u64(const std::vector<uint8_t>& b, size_t off) {
    return (uint64_t)read_u32(b, off) | ((uint64_t)read_u32(b, off+4) << 32);
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        printUsage(argv[0]);
        return 1;
    }

    const char* path = argv[1];
    std::ifstream file(path, std::ios::binary);
    if (!file.is_open()) {
        std::cerr << "Error: cannot open '" << path << "'\n";
        return 1;
    }

    // Read file into byte buffer
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(file)),
                                std::istreambuf_iterator<char>());
    file.close();

    if (bytes.empty()) {
        std::cerr << "Error: file is empty\n";
        return 1;
    }

    std::vector<uint16_t> words;

    bool is_elf = bytes.size() >= 4 && bytes[0] == 0x7F && bytes[1] == 'E' && bytes[2] == 'L' && bytes[3] == 'F';
    if (!is_elf) {
        if (bytes.size() % 2 != 0) bytes.push_back(0);
        words.resize(bytes.size() / 2);
        std::memcpy(words.data(), bytes.data(), bytes.size());
    } else {
        // Minimal ELF loader for .text + .rela.text
        if (bytes.size() < 64) {
            std::cerr << "Error: ELF file too small\n";
            return 1;
        }

        bool is64 = (bytes[4] == 2);
        bool isle = (bytes[5] == 1);
        if (!is64 || !isle) {
            std::cerr << "Error: only ELF64 little-endian is supported\n";
            return 1;
        }

        uint64_t e_shoff = read_u64(bytes, 0x28);
        uint16_t e_shentsize = read_u16(bytes, 0x3A);
        uint16_t e_shnum = read_u16(bytes, 0x3C);
        uint16_t e_shstrndx = read_u16(bytes, 0x3E);

        if (e_shoff + e_shnum * e_shentsize > bytes.size()) {
            std::cerr << "Error: ELF section headers out of range\n";
            return 1;
        }

        uint64_t shstr_offset = read_u64(bytes, e_shoff + e_shentsize * e_shstrndx + 0x18);
        uint64_t shstr_size = read_u64(bytes, e_shoff + e_shentsize * e_shstrndx + 0x20);
        if (shstr_offset + shstr_size > bytes.size()) {
            std::cerr << "Error: .shstrtab out of range\n";
            return 1;
        }

        std::string shstr((const char*)&bytes[shstr_offset], (size_t)shstr_size);

        uint64_t text_offset = 0, text_size = 0;
        uint64_t symtab_offset = 0, symtab_size = 0, symtab_entsize = 0;
        uint64_t strtab_offset = 0, strtab_size = 0;
        uint64_t rela_offset = 0, rela_size = 0;
        // strtab_offset and strtab_size are not needed for emulator currently.
        (void)strtab_offset; (void)strtab_size;

        for (uint16_t i = 0; i < e_shnum; ++i) {
            uint64_t sh_base = e_shoff + (uint64_t)i * e_shentsize;
            uint32_t name_off = read_u32(bytes, sh_base);
            if (name_off >= shstr_size) continue;
            std::string name(&shstr[name_off]);
            uint32_t type = read_u32(bytes, sh_base + 4);
            (void)type;
            uint64_t off = read_u64(bytes, sh_base + 0x18);
            uint64_t siz = read_u64(bytes, sh_base + 0x20);
            uint64_t entsize = read_u64(bytes, sh_base + 0x38);

            if (name == ".text") { text_offset = off; text_size = siz; }
            if (name == ".symtab") { symtab_offset = off; symtab_size = siz; symtab_entsize = entsize; }
            if (name == ".strtab") { strtab_offset = off; strtab_size = siz; }
            if (name == ".rela.text") { rela_offset = off; rela_size = siz; }
        }

        if (text_offset + text_size > bytes.size()) {
            std::cerr << "Error: .text out of range\n";
            return 1;
        }

        // Build symbol table
        struct ElfSym { uint32_t name; unsigned char info; unsigned char other; uint16_t shndx; uint64_t value; uint64_t size; };
        std::vector<ElfSym> syms;
        if (symtab_offset && symtab_size && symtab_entsize == 24) {
            size_t entries = symtab_size / symtab_entsize;
            for (size_t i = 0; i < entries; ++i) {
                uint64_t off = symtab_offset + i * symtab_entsize;
                if (off + 24 > bytes.size()) break;
                ElfSym s;
                s.name = read_u32(bytes, off);
                s.info = bytes[off + 4];
                s.other = bytes[off + 5];
                s.shndx = read_u16(bytes, off + 6);
                s.value = read_u64(bytes, off + 8);
                s.size = read_u64(bytes, off + 16);
                syms.push_back(s);
            }
        }

        auto lookupSymbol = [&](uint32_t idx) -> uint64_t {
            if (idx >= 1 && idx <= syms.size()) {
                return syms[idx-1].value;
            }
            return 0;
        };

        // Starting text bytes
        std::vector<uint8_t> text(bytes.begin() + text_offset, bytes.begin() + text_offset + text_size);

        // Apply relocations if present
        if (rela_offset && rela_size) {
            size_t nrecs = rela_size / 24;
            for (size_t i = 0; i < nrecs; ++i) {
                uint64_t off = rela_offset + i*24;
                if (off + 24 > bytes.size()) break;
                uint64_t r_offset = read_u64(bytes, off);
                uint64_t r_info = read_u64(bytes, off + 8);
                int64_t r_addend = (int64_t)read_u64(bytes, off + 16);
                uint32_t r_sym = (uint32_t)(r_info >> 32);
                uint32_t r_type = (uint32_t)(r_info & 0xFFFFFFFF);

                if (r_offset + 8 > text.size()) continue;

                uint64_t sym_value = lookupSymbol(r_sym);
                uint64_t target = sym_value + r_addend;

                if (r_type == 1) { // PCREL6
                    // instruction at r_offset in .text, which is in bytes.
                    if (r_offset + 2 > text.size()) continue;
                    uint16_t instr = (uint16_t)text[r_offset] | ((uint16_t)text[r_offset+1] << 8);
                    int64_t pc = (int64_t)r_offset;
                    int64_t diff = (int64_t)target - (pc + 2);
                    int64_t rel = diff / 2;
                    if (rel < -32 || rel > 31) {
                        std::cerr << "ELF relocation PCREL6 out of range\n";
                    }
                    uint16_t new_instr = (instr & 0xF00F) | ((uint16_t)(rel & 0x3F) << 4);
                    text[r_offset] = new_instr & 0xFF;
                    text[r_offset+1] = (new_instr >> 8) & 0xFF;
                } else if (r_type == 2) { // ABS64
                    if (r_offset + 8 > text.size()) continue;
                    for (int j = 0; j < 8; ++j) {
                        text[r_offset+j] = (uint8_t)((target >> (8*j)) & 0xFF);
                    }
                }
            }
        }

        if (text.size() % 2 != 0) text.push_back(0);
        words.resize(text.size()/2);
        std::memcpy(words.data(), text.data(), text.size());
    }

    Little64CPU cpu;
    cpu.loadProgram(words);

    SerialDevice* serial = cpu.getSerial();

    while (cpu.isRunning) {
        cpu.cycle();

        if (serial && !serial->txBuffer().empty()) {
            std::cout << serial->txBuffer() << std::flush;
            serial->clearTxBuffer();
        }
    }

    // Flush any remaining serial output
    if (serial && !serial->txBuffer().empty()) {
        std::cout << serial->txBuffer();
        serial->clearTxBuffer();
    }

    std::cout.flush();
    return 0;
}
