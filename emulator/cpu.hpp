#pragma once

#include <cstdint>
#include <vector>
#include "memory_bus.hpp"
#include "serial_device.hpp"

class Little64CPU {
public:
    Little64CPU();
    ~Little64CPU() = default;

    struct Registers {
        // R0 is defined to always be zero, and writes to it are ignored.
        //  This is implemented by just setting regs[0] to zero at the beginning of every instruction execution.
        // R1-R10 are general-purpose registers.
        // R11 and R12 are reserved for now.
        // R13 is the stack pointer (SP) used for function calls and local variable storage.
        // R14 is the link register (LR) used for function calls.
        // R15 is the program counter (PC) and is updated automatically by the CPU when instructions are executed.
        uint64_t regs[16];

        // Flag bits:
        //   bit 0: Zero (Z)  — result was zero
        //   bit 1: Carry (C) — unsigned overflow/borrow
        //   bit 2: Sign (S)  — result was negative (MSB set)
        // JUMP.GT fires when Z=0 and S=0; JUMP.LT fires when S=1.
        uint64_t flags;

        // Special register space and helper methods
        uint64_t cpu_control;
        uint64_t interrupt_table_base;

        uint64_t getSpecialRegister(uint64_t index) const {
            switch (index) {
                case 0: return cpu_control;
                case 1: return interrupt_table_base;
                default: return 0;
            }
        }

        void setSpecialRegister(uint64_t index, uint64_t value) {
            switch (index) {
                case 0: cpu_control = value; break;
                case 1: interrupt_table_base = value; break;
            }
        }
    };

    struct Instruction {
        bool operator==(const Instruction& other) const {
            return _raw == other._raw;
        }

        // bits[15:14]: 0=LS_REG, 1=LS_PCREL, 2=LDI, 3=GP
        uint8_t format = 0;

        // Common to all formats
        uint8_t rd = 0;         // bits[3:0]

        // Formats 00 and 01: LS opcode (4 bits, bits[13:10])
        uint8_t opcode_ls = 0;

        // Format 00 (LS Register)
        uint8_t offset2 = 0;    // bits[9:8]: unsigned, byte offset = offset2 * 2
        uint8_t rs1 = 0;        // bits[7:4]  (also used by format 11)

        // Format 01 (LS PC-Relative)
        int8_t pc_rel = 0;      // bits[9:4]: 6-bit signed, byte offset = pc_rel * 2

        // Format 10 (Load Immediate)
        uint8_t shift = 0;      // bits[13:12]
        uint8_t imm8 = 0;       // bits[11:4]

        // Format 11 (GP ALU)
        uint8_t opcode_gp = 0;  // bits[13:8] (6 bits)
        // rs1 reused at bits[7:4]

        Instruction() = default;
        Instruction(uint16_t raw) : _raw(raw) {
            format = (raw >> 14) & 0x3;
            rd     = raw & 0xF;

            switch (format) {
                case 0: // LS Register
                    opcode_ls = (raw >> 10) & 0xF;
                    offset2   = (raw >> 8)  & 0x3;
                    rs1       = (raw >> 4)  & 0xF;
                    break;
                case 1: { // LS PC-Relative
                    opcode_ls = (raw >> 10) & 0xF;
                    uint8_t raw6 = (raw >> 4) & 0x3F;
                    pc_rel = (raw6 & 0x20) ? (int8_t)(raw6 | 0xC0) : (int8_t)raw6;
                    break;
                }
                case 2: // Load Immediate
                    shift = (raw >> 12) & 0x3;
                    imm8  = (raw >> 4)  & 0xFF;
                    break;
                case 3: // GP ALU
                    opcode_gp = (raw >> 8) & 0x3F;
                    rs1       = (raw >> 4) & 0xF;
                    break;
            }
        }

        uint16_t encode() const {
            uint16_t raw = 0;
            raw |= (format & 0x3) << 14;
            raw |= (rd & 0xF);

            switch (format) {
                case 0:
                    raw |= (opcode_ls & 0xF) << 10;
                    raw |= (offset2   & 0x3) << 8;
                    raw |= (rs1       & 0xF) << 4;
                    break;
                case 1:
                    raw |= (opcode_ls         & 0xF)  << 10;
                    raw |= ((uint8_t)pc_rel   & 0x3F) << 4;
                    break;
                case 2:
                    raw |= (shift & 0x3)  << 12;
                    raw |= (imm8  & 0xFF) << 4;
                    break;
                case 3:
                    raw |= (opcode_gp & 0x3F) << 8;
                    raw |= (rs1       & 0xF)  << 4;
                    break;
            }
            return raw;
        }

    private:
        uint16_t _raw = 0;
    };

    void cycle();
    void dispatchInstruction(const Instruction& instr);

    // Load program words as a ROM region (4K-aligned) at base address.
    // Creates ROM + 64MB RAM + serial device. Resets CPU state.
    void loadProgram(const std::vector<uint16_t>& words, uint64_t base = 0);

    // Resets basic CPU state. Does not modify memory or devices.
    void reset() {
        registers = {};
        isRunning = true;
    }

    // Memory bus access for GUI panels and external tooling
    MemoryBus&       getMemoryBus()       { return _bus; }
    const MemoryBus& getMemoryBus() const { return _bus; }

    // Returns a pointer to the serial device if one is present, or nullptr.
    SerialDevice* getSerial();

    // Public register state for GUI panels
    Registers registers;

    bool isRunning = true;

private:
    void _dispatchLSReg(const Instruction& instr);
    void _dispatchLSPCRel(const Instruction& instr);
    void _dispatchLDI(const Instruction& instr);
    void _dispatchGP(const Instruction& instr);

    void _updateFlags(uint64_t result, bool carry = false);

    uint8_t  _readMemory8 (uint64_t addr) const { return _bus.read8(addr);  }
    void     _writeMemory8(uint64_t addr, uint8_t v)  { _bus.write8(addr, v);  }
    uint16_t _readMemory16(uint64_t addr) const { return _bus.read16(addr); }
    void     _writeMemory16(uint64_t addr, uint16_t v) { _bus.write16(addr, v); }
    uint32_t _readMemory32(uint64_t addr) const { return _bus.read32(addr); }
    void     _writeMemory32(uint64_t addr, uint32_t v) { _bus.write32(addr, v); }
    uint64_t _readMemory64(uint64_t addr) const { return _bus.read64(addr); }
    void     _writeMemory64(uint64_t addr, uint64_t v) { _bus.write64(addr, v); }

    MemoryBus _bus;
};
