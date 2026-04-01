#pragma once

#include "test_harness.hpp"
#include "assembler.hpp"
#include "cpu.hpp"
#include <cstdint>
#include <string>

static constexpr uint64_t FLAG_Z = 1ULL << 0;
static constexpr uint64_t FLAG_C = 1ULL << 1;
static constexpr uint64_t FLAG_S = 1ULL << 2;

static constexpr uint64_t ROM_SIZE = 4096;
static constexpr uint64_t RAM_BASE = ROM_SIZE;

[[maybe_unused]] static Little64CPU::Instruction make_instr(const char* src) {
    Assembler assembler;
    return Little64CPU::Instruction(assembler.assemble(src)[0]);
}

struct ExecResult {
    uint64_t rd_value;
    uint64_t flags;
};

[[maybe_unused]] static ExecResult exec(const char* src, int rd, uint64_t initial) {
    Little64CPU cpu;
    cpu.registers.regs[rd] = initial;
    cpu.dispatchInstruction(make_instr(src));
    return { cpu.registers.regs[rd], cpu.registers.flags };
}

[[maybe_unused]] static Little64CPU run_program(const std::string& src, int max_cycles = 10000) {
    Assembler assembler;
    auto words = assembler.assemble(src);
    Little64CPU cpu;
    cpu.loadProgram(words);
    for (int cycle = 0; cycle < max_cycles && cpu.isRunning; ++cycle) {
        cpu.cycle();
    }
    return cpu;
}
