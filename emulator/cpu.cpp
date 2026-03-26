#include <iostream>
#include "cpu.hpp"

Little64CPU::Little64CPU() {
    // Initialize registers to zero
    for (int i = 0; i < 16; ++i) {
        registers.gpr[i] = 0;
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

