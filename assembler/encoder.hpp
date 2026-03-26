#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>

class Encoder {
public:
    // Initialize static maps from .def files
    static void init();

    // Encode format 00 (LS Register): bits[15:14]=00
    static uint16_t encodeLSReg(uint8_t opcode_ls, uint8_t offset2, uint8_t rs1, uint8_t rd);

    // Encode format 01 (LS PC-Relative): bits[15:14]=01
    static uint16_t encodeLSPCRel(uint8_t opcode_ls, int8_t pc_rel, uint8_t rd);

    // Encode format 10 (Load Immediate): bits[15:14]=10
    static uint16_t encodeLDI(uint8_t shift, uint8_t imm8, uint8_t rd);

    // Encode format 11 (GP ALU): bits[15:14]=11
    static uint16_t encodeGP(uint8_t opcode_gp, uint8_t rs1, uint8_t rd);

    // Opcode lookups
    static uint8_t getLSOpcode(const std::string& mnemonic);
    static uint8_t getGPOpcode(const std::string& mnemonic);
    static uint8_t getGPNumRegs(const std::string& mnemonic);
    static bool isLSMnemonic(const std::string& mnemonic);
    static bool isGPMnemonic(const std::string& mnemonic);
    static bool isLDIMnemonic(const std::string& mnemonic);

private:
    static std::unordered_map<std::string, uint8_t> ls_mnemonics;
    static std::unordered_map<std::string, uint8_t> gp_mnemonics;
    static std::unordered_map<std::string, uint8_t> gp_num_regs;
};
