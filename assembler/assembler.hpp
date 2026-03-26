#pragma once

#include "lexer.hpp"
#include <vector>
#include <unordered_map>
#include <string>
#include <cstdint>

class Assembler {
public:
    // Assemble source code and return the binary output
    // Throws std::runtime_error on any failure
    std::vector<uint16_t> assemble(const std::string& source);

    // Return a string representation of assembled instructions for listing
    std::string getListing() const;

private:
    using SymbolTable = std::unordered_map<std::string, uint16_t>;

    enum class Format { LS_REG, LS_PCREL, LDI, GP };

    struct ParsedInstruction {
        std::string mnemonic;   // base mnemonic, e.g. "LOAD", "JUMP.Z", "LDI", "ADD"
        uint8_t shift = 0;      // LDI only: shift value from .SN suffix (0-3)
        Format detected_format = Format::GP;
        std::vector<Token> operands;
        uint16_t address = 0;
        int line = 0;
    };

    void pass1(const std::vector<Token>& tokens, SymbolTable& symbols);
    void pass2(const std::vector<Token>& tokens, const SymbolTable& symbols,
               std::vector<uint16_t>& output);

    ParsedInstruction parseInstruction(const std::vector<Token>& tokens, size_t& idx,
                                       uint16_t address, int& line_count);

    uint16_t encodeInstruction(const ParsedInstruction& instr, const SymbolTable& symbols,
                               uint16_t current_address);

    uint16_t origin = 0;
    std::vector<ParsedInstruction> instructions;  // for --list output
};
