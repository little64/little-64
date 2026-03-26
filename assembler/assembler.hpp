#pragma once

#include "lexer.hpp"
#include <vector>
#include <unordered_map>
#include <string>
#include <cstdint>

class Assembler {
public:
    // Assemble source code and return the binary output
    // Throws AssemblerError on any failure
    std::vector<uint16_t> assemble(const std::string& source);

    // Return a string representation of assembled instructions for listing
    std::string getListing() const;

private:
    using SymbolTable = std::unordered_map<std::string, uint16_t>;

    struct ParsedInstruction {
        std::string mnemonic;
        uint8_t shift_or_mask = 0;  // parsed from suffix
        bool is_mask = false;        // true = format 4 (T=1, E=1), false = format 3 (T=1, E=0)
        std::vector<Token> operands;
        uint16_t address = 0;
        int line = 0;
    };

    void pass1(const std::vector<Token>& tokens, SymbolTable& symbols);
    void pass2(const std::vector<Token>& tokens, const SymbolTable& symbols,
               std::vector<uint16_t>& output);

    // Parse a single instruction from tokens starting at index, return mnemonic+operands
    // Updates idx to point past the instruction
    ParsedInstruction parseInstruction(const std::vector<Token>& tokens, size_t& idx,
                                       uint16_t address, int& line_count);

    // Encode an instruction given the symbol table
    uint16_t encodeInstruction(const ParsedInstruction& instr, const SymbolTable& symbols,
                               uint16_t current_address);

    uint16_t origin = 0;
    std::vector<ParsedInstruction> instructions;  // for --list output
};
