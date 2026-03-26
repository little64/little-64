#include "encoder.hpp"
#include "opcodes.hpp"
#include <stdexcept>

std::unordered_map<std::string, uint8_t> Encoder::t0_mnemonics;
std::unordered_map<std::string, uint8_t> Encoder::ls_mnemonics;

void Encoder::init() {
    // Build T=0 mnemonic map
#define LITTLE64_T0_OPCODE(name, value, mnemonic) \
    t0_mnemonics[mnemonic] = value;
#include "opcodes_t0.def"
#undef LITTLE64_T0_OPCODE

    // Build T=1 mnemonic map
#define LITTLE64_LS_OPCODE(name, value, mnemonic) \
    ls_mnemonics[mnemonic] = value;
#include "opcodes_ls.def"
#undef LITTLE64_LS_OPCODE
}

uint16_t Encoder::encodeT0(uint8_t opcode, bool is_register_operand,
                           uint8_t rs1_or_pcrel, uint8_t rd) {
    uint16_t raw = 0;
    // type=0 (bit 15)
    // encoding bit 14: 0 for register, 1 for PC-relative
    raw |= (is_register_operand ? 0 : 1) << 14;
    raw |= (opcode & 0xF) << 10;
    raw |= (rs1_or_pcrel & 0x3F) << 4;  // 6 bits for PC-rel, or 4 bits for Rs1 (bits 7-4)
    raw |= (rd & 0xF);
    return raw;
}

uint16_t Encoder::encodeLS_shift(uint8_t opcode, uint8_t shift, uint8_t imm6, uint8_t rd) {
    uint16_t raw = 0;
    raw |= 1 << 15;                     // type=1
    // encoding=0 (bit 14)
    raw |= (opcode & 0x3) << 12;        // 2 bits
    raw |= (shift & 0x3) << 10;
    raw |= (imm6 & 0x3F) << 4;
    raw |= (rd & 0xF);
    return raw;
}

uint16_t Encoder::encodeLS_mask(uint8_t opcode, uint8_t mask, uint8_t pcrel, uint8_t rd) {
    uint16_t raw = 0;
    raw |= 1 << 15;                     // type=1
    raw |= 1 << 14;                     // encoding=1
    raw |= (opcode & 0x3) << 12;        // 2 bits
    raw |= (mask & 0x3) << 10;
    raw |= (pcrel & 0x3F) << 4;
    raw |= (rd & 0xF);
    return raw;
}

uint8_t Encoder::getT0Opcode(const std::string& mnemonic) {
    auto it = t0_mnemonics.find(mnemonic);
    if (it == t0_mnemonics.end()) {
        throw std::runtime_error("Unknown T=0 mnemonic: " + mnemonic);
    }
    return it->second;
}

uint8_t Encoder::getLSOpcode(const std::string& mnemonic) {
    auto it = ls_mnemonics.find(mnemonic);
    if (it == ls_mnemonics.end()) {
        throw std::runtime_error("Unknown load/store mnemonic: " + mnemonic);
    }
    return it->second;
}
