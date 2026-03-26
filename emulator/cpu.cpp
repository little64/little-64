#include <iostream>
#include "cpu.hpp"
#include "opcodes.hpp"

Little64CPU::Little64CPU() {
    // Initialize registers to zero
    for (int i = 0; i < 16; ++i) {
        registers.regs[i] = 0;
    }
}

void Little64CPU::cycle() {
    if(!isRunning) {
        return;
    }

    // Ensure R0 is always zero
    registers.regs[0] = 0;

    // Ensure that the PC is within bounds of memory
    if (registers.regs[15] >= 65536) {
        std::cerr << "PC out of bounds: " << registers.regs[15] << std::endl;
        isRunning = false;
        return;
    }

    // Fetch instruction
    uint16_t instr_word = mem[registers.regs[15]] | (mem[registers.regs[15] + 1] << 8);
    Instruction instr(instr_word);

    // Increment PC for next instruction (will be updated by some instructions)
    registers.regs[15] += 2;

    // Dispatch instruction
    dispatchInstruction(instr);
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

    // Dispatch the instructions based on type
    if (instr.type == 0) {
        _dispatchType0(instr);
    } else {
        _dispatchType1(instr);
    }
}

void Little64CPU::_dispatchType0(const Instruction& instr) {
    // Handle type 0 instructions based on opcode and encoding
    // This is where the actual execution logic for type 0 instructions will go
    // For now, we just print a message
    std::cout << "Executing Type 0 instruction with opcode " << static_cast<int>(instr.opcode) << std::endl;
}

// This function will handle type 1 (load/store) instructions based on opcode and encoding
void Little64CPU::_dispatchType1(const Instruction& instr) {
    uint64_t rd_val = registers.regs[instr.rd];
    uint64_t second;

    if (instr.encoding == 0) {
        second = (static_cast<uint64_t>(instr.imm6) << (instr.shift * 8));
    } else {
        uint64_t second_addr = registers.regs[15] + (static_cast<int16_t>(instr.pc_rel) << 1); // PC-relative address
        second = _readMemory64(second_addr);
    }

    switch(static_cast<LS::Opcode>(instr.opcode)) {
        case LS::Opcode::LOAD: {
            std::cout << "LOAD: R" << instr.rd << " = MEM[0x" << std::hex << second << std::dec << "]" << std::endl;
            registers.regs[instr.rd] = _readMemory64(second);
            break;
        }
        case LS::Opcode::STORE: {
            std::cout << "STORE: MEM[0x" << std::hex << second << std::dec << "] = R" << instr.rd << std::endl;
            uint64_t value = registers.regs[instr.rd];
            for (int i = 0; i < 8; ++i) {
                mem[second + i] = (value >> (i * 8)) & 0xFF;
            }
            break;
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

