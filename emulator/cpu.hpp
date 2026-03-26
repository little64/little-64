#pragma once

#include <cstdint>
#include <vector>

class Little64CPU {
public:
    Little64CPU();
    ~Little64CPU() = default;

    struct Registers {
        // R0 is defined to always be zero, and writes to it are ignored.
        // This is implemented by just setting gpr[0] to zero at the beginning of every instruction execution.
        uint64_t gpr[16];
    };

    struct Instruction {
        bool operator==(const Instruction& other) const {
            return _raw == other._raw;
        }

        bool type = false;
        bool encoding = false;

        uint8_t opcode : 4 = 0; // 2 bits for type 1, 4 bits for type 0

        union {
            uint8_t rs1 : 4 = 0;
            uint16_t imm6 : 6;
            uint16_t pc_rel : 6;
        };

        // Specific to type 1 (load/store) instructions
        union {
            uint8_t shift : 2 = 0; // encode = 0
            uint8_t mask : 2; // encode = 1
        };

        uint16_t rd = 0;

        Instruction() = default;
        Instruction(uint16_t raw) : _raw(raw) {
            type = (raw >> 15) & 0x1;
            encoding = (raw >> 14) & 0x1;
            rd = raw & 0xF;
                
            if(type == 0) {
                opcode = (raw >> 10) & 0xF;
                if(encoding == 0) {
                    rs1 = (raw >> 4) & 0xF;
                } else { // encoding == 1
                    pc_rel = (raw >> 4) & 0x3F;
                }
            } else { // type == 1
                opcode = (raw >> 12) & 0b11;
                if(encoding == 0) {
                    shift = (raw >> 10) & 0b11;
                    imm6 = (raw >> 4) & 0x3F;
                } else { // encoding == 1
                    mask = (raw >> 10) & 0b11;
                    pc_rel = (raw >> 4) & 0x3F;
                }
            }
        }


        uint16_t encode() const {
            uint16_t raw = 0;
            raw |= (type & 0x1) << 15;
            raw |= (encoding & 0x1) << 14;
            raw |= (rd & 0xF);

            if(type == 0) {
                raw |= (opcode & 0xF) << 10;
                if(encoding == 0) {
                    raw |= (rs1 & 0xF) << 4;
                } else { // encoding == 1
                    raw |= (pc_rel & 0x3F) << 4;
                }
            } else { // type == 1
                raw |= (opcode & 0b11) << 12;
                if(encoding == 0) {
                    raw |= (shift & 0b11) << 10;
                    raw |= (imm6 & 0x3F) << 4;
                } else { // encoding == 1
                    raw |= (mask & 0b11) << 10;
                    raw |= (pc_rel & 0x3F) << 4;
                }
            }

            return raw;
        }
    private:
        uint16_t _raw = 0;
    };

    void dispatchInstruction(const Instruction& instr);

    // Memory interface
    void loadProgram(const std::vector<uint16_t>& words, uint16_t base = 0);
    const uint8_t* getMemory() const;
    size_t getMemorySize() const;

    // Public register and PC access for GUI
    Registers registers;
    uint16_t pc = 0;

private:
    uint8_t mem[65536] = {};  // 64KB flat memory, zero-initialized
};
