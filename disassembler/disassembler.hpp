#pragma once

#include <cstdint>
#include <string>
#include <vector>

struct DisassembledInstruction {
    uint16_t address;           // address of this instruction
    uint16_t raw;               // raw 16-bit encoding

    // Decoded fields (matches cpu.hpp Instruction struct layout)
    bool type;                  // bit 15: 0 = T=0, 1 = T=1
    bool encoding;              // bit 14: 0 = E=0, 1 = E=1
    uint8_t opcode;             // 4 bits for T=0, 2 bits for T=1
    uint8_t rd;                 // bits 3-0: destination register (all formats)

    // Format-specific (set based on type/encoding, zero otherwise)
    uint8_t rs1;                // T=0, E=0: source register (bits 7-4)
    int8_t  pc_rel;             // T=0 E=1 / T=1 E=1: signed 6-bit PC-rel field
    uint8_t shift;              // T=1, E=0: byte-lane shift (0-3)
    uint8_t imm6;               // T=1, E=0: 6-bit immediate address
    uint8_t mask;               // T=1, E=1: byte mask (0-3)

    // Derived for display
    uint16_t effective_address;  // for PC-rel: address + 2 + (pc_rel << 1)
    std::string mnemonic;        // e.g. "LOAD", "INC_LOAD", or "" if unknown
    std::string text;            // full disassembly text, e.g. "LOAD.S1 #4, R3"
    bool is_unknown;             // true if opcode not in any .def table
};

class Disassembler {
public:
    // Disassemble one instruction word at a given address.
    // All fields of DisassembledInstruction are populated.
    static DisassembledInstruction disassemble(uint16_t word, uint16_t address);

    // Disassemble a buffer of 16-bit little-endian words starting at base_address.
    static std::vector<DisassembledInstruction>
        disassembleBuffer(const uint16_t* words, size_t count, uint16_t base_address = 0);
};
