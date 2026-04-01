#pragma once
// Shared test infrastructure for Little-64 CPU test suite.
// Include this header in each test_cpu_*.cpp file.
// Each translation unit gets its own static _pass/_fail counters.

#include "support/test_harness.hpp"
#include "assembler.hpp"
#include "cpu.hpp"
#include <cstdint>
#include <string>

// ---------------------------------------------------------------------------
// Flag bit constants (match cpu.cpp)
// ---------------------------------------------------------------------------

static constexpr uint64_t FLAG_Z = 1ULL << 0;   // Zero
static constexpr uint64_t FLAG_C = 1ULL << 1;   // Carry / borrow
static constexpr uint64_t FLAG_S = 1ULL << 2;   // Sign (bit 63 set)

// ---------------------------------------------------------------------------
// Memory layout constants
// ROM is padded to 4 KB, so RAM starts immediately after when base = 0.
// ---------------------------------------------------------------------------

static constexpr uint64_t ROM_SIZE = 4096;
static constexpr uint64_t RAM_BASE = ROM_SIZE;   // 0x1000

// ---------------------------------------------------------------------------
// Single-instruction helpers (no memory needed — use dispatchInstruction)
// ---------------------------------------------------------------------------

// Assemble a single-instruction source line and return the decoded Instruction.
// The encoding is derived from the assembler, so tests survive opcode renumbering.
[[maybe_unused]] static Little64CPU::Instruction make_instr(const char* src) {
    Assembler a;
    return Little64CPU::Instruction(a.assemble(src)[0]);
}

// Result of executing one instruction
struct ExecResult {
    uint64_t rd_value;   // destination register after dispatch
    uint64_t flags;      // full flags word after dispatch
};

// Execute one assembled instruction on a fresh CPU with registers[rd] pre-loaded.
// For RS1_RD instructions that also read Rs1, set the CPU registers manually first
// and call cpu.dispatchInstruction directly instead.
[[maybe_unused]] static ExecResult exec(const char* src, int rd, uint64_t initial) {
    Little64CPU cpu;
    cpu.registers.regs[rd] = initial;
    cpu.dispatchInstruction(make_instr(src));
    return { cpu.registers.regs[rd], cpu.registers.flags };
}

// ---------------------------------------------------------------------------
// Full-program helpers (memory-backed — use loadProgram + cycle)
// ---------------------------------------------------------------------------

// Assemble a multi-instruction program, load it, run until STOP or max_cycles.
// Returns the CPU object so callers can inspect registers and memory.
[[maybe_unused]] static Little64CPU run_program(const std::string& src, int max_cycles = 10000) {
    Assembler a;
    auto words = a.assemble(src);
    Little64CPU cpu;
    cpu.loadProgram(words);
    for (int i = 0; i < max_cycles && cpu.isRunning; ++i)
        cpu.cycle();
    return cpu;
}
