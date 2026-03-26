#pragma once

#include <cstdint>
#include <string>
#include <vector>

struct DisassembledInstruction {
    uint16_t address;           // address of this instruction
    uint16_t raw;               // raw 16-bit encoding
    bool is_unknown;            // true if opcode not in any .def table

    // Decoded fields
    uint8_t format;             // bits[15:14]: 0=LS_REG, 1=LS_PCREL, 2=LDI, 3=GP
    uint8_t rd;                 // bits[3:0]: destination (or source for stores)

    // Formats 00 and 01
    uint8_t opcode_ls;          // bits[13:10]: LS opcode (4 bits)

    // Format 00 only
    uint8_t offset2;            // bits[9:8]: byte offset = offset2 * 2
    uint8_t rs1;                // bits[7:4]: base register (also used by format 11)

    // Format 01 only
    int8_t  pc_rel;             // bits[9:4]: signed 6-bit; byte offset = pc_rel * 2
    uint16_t effective_address; // address + 2 + (pc_rel * 2)

    // Format 10 only
    uint8_t shift;              // bits[13:12]
    uint8_t imm8;               // bits[11:4]

    // Format 11 only
    uint8_t opcode_gp;          // bits[13:8]: GP opcode (6 bits)

    // Display
    std::string mnemonic;       // e.g. "LOAD", "JUMP.Z", "LDI", "ADD"
    std::string text;           // full disassembly text
};

class Disassembler {
public:
    // Disassemble one instruction word at a given address.
    static DisassembledInstruction disassemble(uint16_t word, uint16_t address);

    // Disassemble a buffer of 16-bit little-endian words starting at base_address.
    static std::vector<DisassembledInstruction>
        disassembleBuffer(const uint16_t* words, size_t count, uint16_t base_address = 0);
};
