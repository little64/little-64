#pragma once
// Shared test infrastructure for Little-64 CPU test suite.
// Include this header in each test_cpu_*.cpp file.
// Each translation unit gets its own static _pass/_fail counters.

#include "assembler.hpp"
#include "cpu.hpp"
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <string>

// ---------------------------------------------------------------------------
// Counters (static = per-TU; each binary has exactly one set)
// ---------------------------------------------------------------------------

static int _pass = 0, _fail = 0;

// ---------------------------------------------------------------------------
// Assertion macros
// ---------------------------------------------------------------------------

#define CHECK_EQ(actual, expected, msg)                                         \
    do {                                                                        \
        uint64_t _a = static_cast<uint64_t>(actual);                            \
        uint64_t _e = static_cast<uint64_t>(expected);                          \
        if (_a == _e) {                                                         \
            _pass++;                                                            \
        } else {                                                                \
            std::fprintf(stderr, "FAIL [%s:%d] %s\n"                           \
                                 "  expected: 0x%016llX\n"                      \
                                 "  actual  : 0x%016llX\n",                     \
                         __FILE__, __LINE__, (msg),                             \
                         static_cast<unsigned long long>(_e),                   \
                         static_cast<unsigned long long>(_a));                  \
            _fail++;                                                            \
        }                                                                       \
    } while (0)

#define CHECK_TRUE(cond, msg)  CHECK_EQ(!!(cond), 1ULL, (msg))
#define CHECK_FALSE(cond, msg) CHECK_EQ(!!(cond), 0ULL, (msg))

#define CHECK_THROWS(expr, msg)                                                 \
    do {                                                                        \
        bool _threw = false;                                                    \
        try { (expr); } catch (...) { _threw = true; }                          \
        if (_threw) {                                                           \
            _pass++;                                                            \
        } else {                                                                \
            std::fprintf(stderr, "FAIL [%s:%d] expected exception: %s\n",      \
                         __FILE__, __LINE__, (msg));                            \
            _fail++;                                                            \
        }                                                                       \
    } while (0)

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
static Little64CPU::Instruction make_instr(const char* src) {
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
static ExecResult exec(const char* src, int rd, uint64_t initial) {
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
static Little64CPU run_program(const std::string& src, int max_cycles = 10000) {
    Assembler a;
    auto words = a.assemble(src);
    Little64CPU cpu;
    cpu.loadProgram(words);
    for (int i = 0; i < max_cycles && cpu.isRunning; ++i)
        cpu.cycle();
    return cpu;
}

// ---------------------------------------------------------------------------
// Summary helper (call at end of main)
// ---------------------------------------------------------------------------

static int print_summary() {
    std::printf("\n=== Results: %d passed, %d failed ===\n", _pass, _fail);
    return _fail != 0 ? 1 : 0;
}
