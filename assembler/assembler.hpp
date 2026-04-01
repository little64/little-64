#pragma once

#include "lexer.hpp"
#include <vector>
#include <unordered_map>
#include <string>
#include <cstdint>

// A data directive item produced by pass1 and consumed by pass2.
struct DataDirective {
    enum class Kind { Byte, Short, Int, Long, Ascii, Asciiz };
    Kind kind;
    uint64_t value = 0;    // Byte / Short / Int / Long
    std::string text;      // Ascii / Asciiz (unescaped content)
    bool isSymbol = false; // .long SYMBOL
    std::string symbol;
    uint16_t address = 0;  // byte address at point of emission (from pass1)
    int line = 0;
};

struct SymbolInfo {
    uint16_t value = 0;
    bool defined = false;
    bool global = false;
};

// Instruction encoding format, determined during parsing.
enum class Format { LS_REG, LS_PCREL, LDI, GP, UJMP };

// A fully-parsed instruction ready for pass2 encoding.
struct ParsedInstruction {
    std::string mnemonic;   // base mnemonic, e.g. "LOAD", "JUMP.Z", "LDI", "ADD"
    uint8_t shift = 0;      // LDI only: shift value from .SN suffix (0-3)
    Format detected_format = Format::GP;
    std::vector<Token> operands;
    uint16_t address = 0;   // byte address assigned in pass1 (accounts for .org)
    int line = 0;
};

class Assembler {
public:
    enum class OutputFormat {
        Raw,
        Elf
    };

    struct ElfOptions {
        // future extensions (target architecture, relocation behavior) can go here
    };

    enum class RelocType : uint32_t {
        // Values match the LLVM ELF relocation numbers (ELFRelocs/Little64.def)
        // so that assembler-emitted objects are compatible with LLVM-compiled objects.
        ABS64   = 1,  // R_LITTLE64_ABS64  — 64-bit absolute address
        ABS32   = 2,  // R_LITTLE64_ABS32  — 32-bit absolute address (reserved, unused by assembler)
        PCREL6  = 3,  // R_LITTLE64_PCREL6  — 6-bit PC-relative instruction-unit offset
        PCREL10 = 4,  // R_LITTLE64_PCREL10 — 10-bit PC-relative offset for JUMP.* opcodes
        PCREL13 = 5,  // R_LITTLE64_PCREL13 — 13-bit PC-relative offset for unconditional JUMP
    };

    struct RelocEntry {
        uint64_t offset; // byte offset within .text or .data
        std::string symbol;
        RelocType type;
        int64_t addend;
    };

    // Assemble source code and return the binary output
    // Throws std::runtime_error on any failure
    std::vector<uint16_t> assemble(const std::string& source);

    // Assemble source code and return ELF object bytes
    std::vector<uint8_t> assembleElf(const std::string& source, const ElfOptions& opts = {});

    // Return a string representation of assembled instructions for listing
    std::string getListing() const;

    // Return all known mnemonics (real instructions + pseudo-instructions).
    // Used by the GUI panel for syntax highlighting — call this instead of
    // maintaining a separate hardcoded list.
    static std::vector<std::string> getAllMnemonics();

private:
    using SymbolTable = std::unordered_map<std::string, SymbolInfo>;

    // A single item to be emitted: either an instruction or a data directive.
    // Items are stored in source order so pass2 can emit them interleaved.
public:
    struct EmitItem {
        bool is_instruction = true;
        ParsedInstruction instr;  // valid when is_instruction == true
        DataDirective data;       // valid when is_instruction == false
    };

private:
    void pass1(const std::vector<Token>& tokens, SymbolTable& symbols);
    void pass2(const SymbolTable& symbols, std::vector<uint16_t>& output,
               bool elf_mode = false, std::vector<RelocEntry>* out_relocs = nullptr);

    ParsedInstruction parseInstruction(const std::vector<Token>& tokens, size_t& idx,
                                       uint16_t address, int& line_count);

    uint16_t encodeInstruction(const ParsedInstruction& instr, const SymbolTable& symbols,
                               uint16_t current_address, bool elf_mode = false);

    uint16_t origin = 0;
    std::vector<EmitItem> emit_items;  // populated by pass1, consumed by pass2
};
