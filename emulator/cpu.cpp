#include <iostream>
#include "cpu.hpp"

Little64CPU::Little64CPU() {
    // Initialize registers to zero
    for (int i = 0; i < 16; ++i) {
        registers.regs[i] = 0;
    }
}

void Little64CPU::dispatchInstruction(const Instruction& instr) {
    // For now, just print the instruction details for debugging
    std::cout << "Dispatching instruction: " << std::hex << instr.encode() << std::dec << std::endl;
    std::cout << "Type: " << instr.type << ", Encoding: " << instr.encoding
              << ", Opcode: " << static_cast<int>(instr.opcode)
              << ", Rd: " << instr.rd << std::endl;

    if(instr.type == 0) {
        if(instr.encoding == 0) {
            std::cout << "Rs1: " << static_cast<int>(instr.rs1) << std::endl;
        } else {
            std::cout << "PC Rel: " << static_cast<int>(instr.pc_rel) << std::endl;
        }
    } else {
        if(instr.encoding == 0) {
            std::cout << "Shift: " << static_cast<int>(instr.shift)
                      << ", Imm6: " << static_cast<int>(instr.imm6) << std::endl;
        } else {
            std::cout << "Mask: " << static_cast<int>(instr.mask)
                      << ", PC Rel: " << static_cast<int>(instr.pc_rel) << std::endl;
        }
    }
}

void Little64CPU::loadProgram(const std::vector<uint16_t>& words, uint16_t base) {
    for (size_t i = 0; i < words.size() && base + i * 2 + 1 < 65536; ++i) {
        uint16_t word = words[i];
        mem[base + i * 2] = word & 0xFF;          // little-endian: low byte first
        mem[base + i * 2 + 1] = (word >> 8) & 0xFF;
    }
}

const uint8_t* Little64CPU::getMemory() const {
    return mem;
}

size_t Little64CPU::getMemorySize() const {
    return 65536;
}

