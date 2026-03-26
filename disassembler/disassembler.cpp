#include "disassembler.hpp"
#include "opcodes.hpp"
#include <sstream>
#include <iomanip>
#include <unordered_map>

// Build opcode lookup tables from the same .def files (reverse direction: opcode → mnemonic)
static const std::unordered_map<uint8_t, std::string> kT0Opcodes = {
#define LITTLE64_T0_OPCODE(name, value, mnemonic) { value, mnemonic },
#include "opcodes_t0.def"
#undef LITTLE64_T0_OPCODE
};

static const std::unordered_map<uint8_t, std::string> kLSOpcodes = {
#define LITTLE64_LS_OPCODE(name, value, mnemonic) { value, mnemonic },
#include "opcodes_ls.def"
#undef LITTLE64_LS_OPCODE
};

// Helper: sign-extend a 6-bit value to a signed byte
static int8_t signExtend6(uint8_t val) {
    if (val & 0x20) {  // bit 5 set
        return -(int8_t)(64 - val);
    }
    return (int8_t)val;
}

// Helper: convert mask bits to string representation
static std::string maskToString(uint8_t mask) {
    switch (mask) {
        case 0: return "0";
        case 1: return "B";
        case 2: return "W";
        case 3: return "BW";
        default: return "";
    }
}

DisassembledInstruction Disassembler::disassemble(uint16_t word, uint16_t address) {
    DisassembledInstruction result;
    result.address = address;
    result.raw = word;
    result.is_unknown = false;

    // Decode the instruction (mirror of cpu.hpp's Instruction(uint16_t raw) constructor)
    result.type = (word >> 15) & 0x1;
    result.encoding = (word >> 14) & 0x1;
    result.rd = word & 0xF;

    std::ostringstream oss;
    std::string mnemonic;

    if (result.type == 0) {
        // T=0: register or PC-relative
        result.opcode = (word >> 10) & 0xF;

        // Look up mnemonic
        auto it = kT0Opcodes.find(result.opcode);
        if (it == kT0Opcodes.end()) {
            mnemonic = "";
            result.is_unknown = true;
        } else {
            mnemonic = it->second;
        }
        result.mnemonic = mnemonic;

        if (result.encoding == 0) {
            // E=0: register format
            result.rs1 = (word >> 4) & 0xF;
            if (result.is_unknown) {
                oss << ".word 0x" << std::hex << std::setw(4) << std::setfill('0') << word;
            } else {
                oss << mnemonic << " R" << (int)result.rs1 << ", R" << (int)result.rd;
            }
        } else {
            // E=1: PC-relative format
            uint8_t pc_rel_raw = (word >> 4) & 0x3F;
            result.pc_rel = signExtend6(pc_rel_raw);
            result.effective_address = address + 2 + ((uint32_t)result.pc_rel << 1);

            if (result.is_unknown) {
                oss << ".word 0x" << std::hex << std::setw(4) << std::setfill('0') << word;
            } else {
                oss << mnemonic << " @";
                if (result.pc_rel >= 0) {
                    oss << "+" << (int)result.pc_rel;
                } else {
                    oss << (int)result.pc_rel;
                }
                oss << ", R" << (int)result.rd;
            }
        }
    } else {
        // T=1: load/store
        result.opcode = (word >> 12) & 0x3;

        // Look up mnemonic
        auto it = kLSOpcodes.find(result.opcode);
        if (it == kLSOpcodes.end()) {
            mnemonic = "";
            result.is_unknown = true;
        } else {
            mnemonic = it->second;
        }
        result.mnemonic = mnemonic;

        if (result.encoding == 0) {
            // E=0: shift format
            result.shift = (word >> 10) & 0x3;
            result.imm6 = (word >> 4) & 0x3F;

            if (result.is_unknown) {
                oss << ".word 0x" << std::hex << std::setw(4) << std::setfill('0') << word;
            } else {
                oss << mnemonic;
                if (result.shift > 0) {
                    oss << ".S" << (int)result.shift;
                }
                oss << " #" << std::dec << (int)result.imm6 << ", R" << (int)result.rd;
            }
        } else {
            // E=1: mask format
            result.mask = (word >> 10) & 0x3;
            uint8_t pc_rel_raw = (word >> 4) & 0x3F;
            result.pc_rel = signExtend6(pc_rel_raw);
            result.effective_address = address + 2 + ((uint32_t)result.pc_rel << 1);

            if (result.is_unknown) {
                oss << ".word 0x" << std::hex << std::setw(4) << std::setfill('0') << word;
            } else {
                oss << mnemonic << "[" << maskToString(result.mask) << "] @";
                if (result.pc_rel >= 0) {
                    oss << "+" << (int)result.pc_rel;
                } else {
                    oss << (int)result.pc_rel;
                }
                oss << std::dec << ", R" << (int)result.rd;
            }
        }
    }

    result.text = oss.str();
    return result;
}

std::vector<DisassembledInstruction>
    Disassembler::disassembleBuffer(const uint16_t* words, size_t count, uint16_t base_address) {
    std::vector<DisassembledInstruction> result;
    result.reserve(count);
    for (size_t i = 0; i < count; ++i) {
        result.push_back(disassemble(words[i], base_address + (i * 2)));
    }
    return result;
}
