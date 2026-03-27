#include "encoder.hpp"
#include "opcodes.hpp"
#include <stdexcept>

std::unordered_map<std::string, uint8_t> Encoder::ls_mnemonics;
std::unordered_map<std::string, uint8_t> Encoder::gp_mnemonics;
std::unordered_map<std::string, uint8_t> Encoder::gp_num_regs;

void Encoder::init() {
#define LITTLE64_LS_OPCODE(name, value, mnemonic) \
    ls_mnemonics[mnemonic] = value;
#include "opcodes_ls.def"
#undef LITTLE64_LS_OPCODE

#define LITTLE64_GP_OPCODE(name, value, mnemonic, nregs) \
    gp_mnemonics[mnemonic] = value; \
    gp_num_regs[mnemonic]  = nregs;
#include "opcodes_gp.def"
#undef LITTLE64_GP_OPCODE
}

std::vector<std::string> Encoder::getMnemonics() {
    std::vector<std::string> result;
    for (const auto& kv : ls_mnemonics) result.push_back(kv.first);
    for (const auto& kv : gp_mnemonics) result.push_back(kv.first);
    return result;
}

// Format 00: bits[15:14]=00
uint16_t Encoder::encodeLSReg(uint8_t opcode_ls, uint8_t offset2, uint8_t rs1, uint8_t rd) {
    uint16_t raw = 0;
    // bits[15:14] = 00 (format 0, already zero)
    raw |= (opcode_ls & 0xF) << 10;
    raw |= (offset2   & 0x3) << 8;
    raw |= (rs1       & 0xF) << 4;
    raw |= (rd        & 0xF);
    return raw;
}

// Format 01: bits[15:14]=01
uint16_t Encoder::encodeLSPCRel(uint8_t opcode_ls, int8_t pc_rel, uint8_t rd) {
    uint16_t raw = 0;
    raw |= 1 << 14;                          // bits[15:14]=01
    raw |= (opcode_ls       & 0xF)  << 10;
    raw |= ((uint8_t)pc_rel & 0x3F) << 4;   // 6-bit signed, mask handles negative values
    raw |= (rd              & 0xF);
    return raw;
}

// Format 10: bits[15:14]=10
uint16_t Encoder::encodeLDI(uint8_t shift, uint8_t imm8, uint8_t rd) {
    uint16_t raw = 0;
    raw |= 2 << 14;              // bits[15:14]=10
    raw |= (shift & 0x3)  << 12;
    raw |= (imm8  & 0xFF) << 4;
    raw |= (rd    & 0xF);
    return raw;
}

// Format 11: bits[15:14]=11
uint16_t Encoder::encodeGP(uint8_t opcode_gp, uint8_t rs1, uint8_t rd) {
    uint16_t raw = 0;
    raw |= 3 << 14;              // bits[15:14]=11
    raw |= (opcode_gp & 0x3F) << 8;
    raw |= (rs1       & 0xF)  << 4;
    raw |= (rd        & 0xF);
    return raw;
}

uint8_t Encoder::getLSOpcode(const std::string& mnemonic) {
    auto it = ls_mnemonics.find(mnemonic);
    if (it == ls_mnemonics.end())
        throw std::runtime_error("Unknown LS mnemonic: " + mnemonic);
    return it->second;
}

uint8_t Encoder::getGPOpcode(const std::string& mnemonic) {
    auto it = gp_mnemonics.find(mnemonic);
    if (it == gp_mnemonics.end())
        throw std::runtime_error("Unknown GP mnemonic: " + mnemonic);
    return it->second;
}

uint8_t Encoder::getGPNumRegs(const std::string& mnemonic) {
    auto it = gp_num_regs.find(mnemonic);
    if (it == gp_num_regs.end())
        throw std::runtime_error("Unknown GP mnemonic: " + mnemonic);
    return it->second;
}

bool Encoder::isLSMnemonic(const std::string& mnemonic) {
    return ls_mnemonics.count(mnemonic) > 0;
}

bool Encoder::isGPMnemonic(const std::string& mnemonic) {
    return gp_mnemonics.count(mnemonic) > 0;
}

bool Encoder::isLDIMnemonic(const std::string& mnemonic) {
    return mnemonic == "LDI";
}
