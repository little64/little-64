#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>
#include "opcodes.hpp"

class Encoder {
public:
    // Initialize static maps from .def files
    static void init();

    // Encode format 00 (LS Register): bits[15:14]=00
    static uint16_t encodeLSReg(uint8_t opcode_ls, uint8_t offset2, uint8_t rs1, uint8_t rd);

    // Encode format 01 (LS PC-Relative): bits[15:14]=01 (non-JUMP opcodes)
    static uint16_t encodeLSPCRel(uint8_t opcode_ls, int8_t pc_rel, uint8_t rd);

    // Encode format 01 (LS PC-Relative, JUMP.* opcodes): 10-bit offset, Rd implicit = R15
    static uint16_t encodeLSPCRelJump(uint8_t opcode_ls, int16_t pc_rel10);

    // Encode format 10 (Load Immediate): bits[15:14]=10
    static uint16_t encodeLDI(uint8_t shift, uint8_t imm8, uint8_t rd);

    // Encode format 110 (GP ALU): bits[15:13]=110
    static uint16_t encodeGP(uint8_t opcode_gp, uint8_t rs1, uint8_t rd);

    // Encode format 111 (Unconditional PC-relative jump): bits[15:13]=111
    static uint16_t encodeUJMP(int16_t pc_rel13);

    // Opcode lookups
    static uint8_t getLSOpcode(const std::string& mnemonic);
    static uint8_t getGPOpcode(const std::string& mnemonic);
    static GP::Encoding getGPEncoding(const std::string& mnemonic);
    static bool isLSMnemonic(const std::string& mnemonic);
    static bool isGPMnemonic(const std::string& mnemonic);
    static bool isLDIMnemonic(const std::string& mnemonic);

    // Return all real-instruction mnemonics from the LS and GP maps.
    static std::vector<std::string> getMnemonics();

private:
    static std::unordered_map<std::string, uint8_t> ls_mnemonics;
    static std::unordered_map<std::string, uint8_t> gp_mnemonics;
    static std::unordered_map<std::string, GP::Encoding> gp_encoding;
};
