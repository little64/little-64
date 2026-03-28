#include "disassembler.hpp"
#include "opcodes.hpp"
#include <sstream>
#include <iomanip>
#include <unordered_map>

// Reverse lookup: opcode value → mnemonic string
static const std::unordered_map<uint8_t, std::string> kLSOpcodes = {
#define LITTLE64_LS_OPCODE(name, value, mnemonic) { value, mnemonic },
#include "opcodes_ls.def"
#undef LITTLE64_LS_OPCODE
};

static const std::unordered_map<uint8_t, std::string> kGPOpcodes = {
#define LITTLE64_GP_OPCODE(name, value, mnemonic, num_regs) { value, mnemonic },
#include "opcodes_gp.def"
#undef LITTLE64_GP_OPCODE
};

static const std::unordered_map<uint8_t, GP::Encoding> kGPEncoding = {
#define LITTLE64_GP_OPCODE(name, value, mnemonic, enc) { value, static_cast<GP::Encoding>(enc) },
#include "opcodes_gp.def"
#undef LITTLE64_GP_OPCODE
};

DisassembledInstruction Disassembler::disassemble(uint16_t word, uint16_t address) {
    DisassembledInstruction result = {};
    result.address    = address;
    result.raw        = word;
    result.is_unknown = false;

    result.format = (word >> 14) & 0x3;
    result.rd     = word & 0xF;

    std::ostringstream oss;

    switch (result.format) {
        case 0: { // LS Register
            result.opcode_ls = (word >> 10) & 0xF;
            result.offset2   = (word >> 8)  & 0x3;
            result.rs1       = (word >> 4)  & 0xF;

            auto it = kLSOpcodes.find(result.opcode_ls);
            if (it == kLSOpcodes.end()) {
                result.is_unknown = true;
                oss << ".word 0x" << std::hex << std::setw(4) << std::setfill('0') << word;
                break;
            }
            result.mnemonic = it->second;

            if (result.mnemonic == "PUSH" || result.mnemonic == "POP") {
                oss << result.mnemonic << " R" << (int)result.rs1 << ", R" << (int)result.rd;
            } else if (result.mnemonic == "MOVE") {
                oss << "MOVE R" << (int)result.rs1;
                if (result.offset2 > 0)
                    oss << "+" << (int)(result.offset2 * 2);
                oss << ", R" << (int)result.rd;
            } else {
                oss << result.mnemonic << " [R" << (int)result.rs1;
                if (result.offset2 > 0)
                    oss << "+" << (int)(result.offset2 * 2);
                oss << "], R" << (int)result.rd;
            }
            break;
        }
        case 1: { // LS PC-Relative
            result.opcode_ls = (word >> 10) & 0xF;

            auto it = kLSOpcodes.find(result.opcode_ls);
            if (it == kLSOpcodes.end()) {
                result.is_unknown = true;
                oss << ".word 0x" << std::hex << std::setw(4) << std::setfill('0') << word;
                break;
            }
            result.mnemonic = it->second;

            if (result.opcode_ls >= 11 && result.opcode_ls <= 15) {
                // JUMP.* opcodes: 10-bit signed offset in bits[9:0], Rd implicit = R15
                uint16_t raw10 = word & 0x3FF;
                result.pc_rel = (raw10 & 0x200) ? (int16_t)(raw10 | 0xFC00) : (int16_t)raw10;
                result.rd = 15;
                result.effective_address = address + 2 + (int16_t)result.pc_rel * 2;

                oss << result.mnemonic << " @";
                if (result.pc_rel >= 0)
                    oss << "+" << (int)result.pc_rel;
                else
                    oss << (int)result.pc_rel;
                oss << std::dec << "  ; 0x" << std::hex << std::setw(4) << std::setfill('0')
                    << result.effective_address;
            } else {
                uint8_t raw6 = (word >> 4) & 0x3F;
                result.pc_rel = (raw6 & 0x20) ? (int16_t)(int8_t)(raw6 | 0xC0) : (int16_t)raw6;
                result.effective_address = address + 2 + (int16_t)result.pc_rel * 2;

                oss << result.mnemonic << " @";
                if (result.pc_rel >= 0)
                    oss << "+" << (int)result.pc_rel;
                else
                    oss << (int)result.pc_rel;
                oss << ", R" << (int)result.rd;
                oss << std::dec << "  ; 0x" << std::hex << std::setw(4) << std::setfill('0')
                    << result.effective_address;
            }
            break;
        }
        case 2: { // Load Immediate
            result.shift    = (word >> 12) & 0x3;
            result.imm8     = (word >> 4)  & 0xFF;
            result.mnemonic = "LDI";

            oss << "LDI";
            if (result.shift > 0)
                oss << ".S" << (int)result.shift;
            oss << " #0x" << std::hex << (int)result.imm8
                << std::dec << ", R" << (int)result.rd;
            break;
        }
        case 3: { // GP ALU
            result.opcode_gp = (word >> 8) & 0x3F;
            result.rs1       = (word >> 4) & 0xF;

            auto it = kGPOpcodes.find(result.opcode_gp);
            if (it == kGPOpcodes.end()) {
                result.is_unknown = true;
                oss << ".word 0x" << std::hex << std::setw(4) << std::setfill('0') << word;
                break;
            }
            result.mnemonic = it->second;

            GP::Encoding enc = kGPEncoding.at(result.opcode_gp);
            oss << result.mnemonic;
            switch (enc) {
                case GP::Encoding::RS1_RD:
                    oss << " R" << (int)result.rs1 << ", R" << (int)result.rd;
                    break;
                case GP::Encoding::RD:
                    oss << " R" << (int)result.rd;
                    break;
                case GP::Encoding::IMM4_RD:
                    oss << " #" << (int)result.rs1 << ", R" << (int)result.rd;
                    break;
                case GP::Encoding::NONE:
                    break;
            }
            break;
        }
    }

    result.text = oss.str();
    return result;
}

std::vector<DisassembledInstruction>
    Disassembler::disassembleBuffer(const uint16_t* words, size_t count, uint16_t base_address) {
    std::vector<DisassembledInstruction> result;
    result.reserve(count);
    for (size_t i = 0; i < count; ++i)
        result.push_back(disassemble(words[i], base_address + (uint16_t)(i * 2)));
    return result;
}
