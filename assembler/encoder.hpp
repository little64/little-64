#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>

class Encoder {
public:
    // Initialize static maps from .def files
    static void init();

    // Encode T=0 instruction (shared opcode space)
    // is_register_operand: true if second operand is Rs1, false if PC-relative
    static uint16_t encodeT0(uint8_t opcode, bool is_register_operand,
                             uint8_t rs1_or_pcrel, uint8_t rd);

    // Encode T=1, E=0 (load/store with shift)
    static uint16_t encodeLS_shift(uint8_t opcode, uint8_t shift, uint8_t imm6, uint8_t rd);

    // Encode T=1, E=1 (load/store with mask)
    static uint16_t encodeLS_mask(uint8_t opcode, uint8_t mask, uint8_t pcrel, uint8_t rd);

    // Get T=0 opcode from mnemonic
    static uint8_t getT0Opcode(const std::string& mnemonic);

    // Get T=1 opcode from mnemonic
    static uint8_t getLSOpcode(const std::string& mnemonic);

private:
    static std::unordered_map<std::string, uint8_t> t0_mnemonics;
    static std::unordered_map<std::string, uint8_t> ls_mnemonics;
};
