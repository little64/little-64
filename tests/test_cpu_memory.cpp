#include "support/cpu_test_helpers.hpp"

// Memory instructions: LOAD/STORE (64-bit), BYTE_LOAD/STORE, SHORT_LOAD/STORE,
//                      WORD_LOAD/STORE, PUSH/POP, MOVE.
//
// All tests use run_program() — memory access requires a real memory bus.
// RAM starts at RAM_BASE (0x1000) when loadProgram is called at base 0.
//
// Address construction: use two LDI instructions to build 0x1000.
//   LDI #0x00, Rx       → Rx = 0x00
//   LDI.S1 #0x10, Rx    → Rx |= 0x1000  →  Rx = 0x1000

static const char* const LOAD_ADDR =
    "LDI #0x00, R15\n"
    "LDI.S1 #0x10, R15\n";   // R15 = RAM_BASE — only used as a temp before STOP in helpers

// Reusable snippet that sets R14 = 0x1000 (RAM base address for test use)
static const std::string addr_setup =
    "LDI #0x00, R14\n"
    "LDI.S1 #0x10, R14\n";   // R14 = 0x1000

// ---------------------------------------------------------------------------
// LOAD / STORE (64-bit)
// ---------------------------------------------------------------------------
static void test_load_store_64() {
    // Round-trip: store value at 0x1000, load it back into R2
    auto cpu = run_program(
        addr_setup +
        "LDI #0x42, R1\n"
        "STORE [R14], R1\n"
        "LOAD  [R14], R2\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], 0x42ULL, "STORE+LOAD 64: round-trip 0x42");

    // Zero value
    cpu = run_program(
        addr_setup +
        "LDI #0x00, R1\n"
        "STORE [R14], R1\n"
        "LOAD  [R14], R2\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], 0ULL, "STORE+LOAD 64: round-trip 0");

    // Different offset: +6 bytes (max valid byte offset for LS instructions)
    cpu = run_program(
        addr_setup +
        "LDI #0x55, R1\n"
        "STORE [R14+6], R1\n"
        "LOAD  [R14+6], R2\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], 0x55ULL, "STORE+LOAD 64: offset +6");

    // UINT64_MAX round-trip via LDI64
    cpu = run_program(
        addr_setup +
        "LDI64 #0xFFFFFFFFFFFFFFFF, R1\n"
        "STORE [R14], R1\n"
        "LOAD  [R14], R2\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], UINT64_MAX, "STORE+LOAD 64: UINT64_MAX");
}

// ---------------------------------------------------------------------------
// BYTE_LOAD / BYTE_STORE
// ---------------------------------------------------------------------------
static void test_byte_load_store() {
    // Store and load single byte, zero-extended
    auto cpu = run_program(
        addr_setup +
        "LDI #0xAB, R1\n"
        "BYTE_STORE [R14], R1\n"
        "BYTE_LOAD  [R14], R2\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], 0xABULL, "BYTE_STORE+BYTE_LOAD: round-trip");

    // Zero-extension: upper 56 bits must be 0
    cpu = run_program(
        addr_setup +
        "LDI64 #0xFFFFFFFFFFFFFFFF, R1\n"
        "BYTE_STORE [R14], R1\n"     // only stores low byte 0xFF
        "BYTE_LOAD  [R14], R2\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], 0xFFULL, "BYTE_LOAD: zero-extended");

    // Byte at +2 offset does not clobber byte at +0
    cpu = run_program(
        addr_setup +
        "LDI #0x11, R1\n"
        "BYTE_STORE [R14], R1\n"
        "LDI #0x22, R1\n"
        "BYTE_STORE [R14+2], R1\n"
        "BYTE_LOAD  [R14], R2\n"     // should still be 0x11
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], 0x11ULL, "BYTE_STORE: adjacent bytes independent");
}

// ---------------------------------------------------------------------------
// SHORT_LOAD / SHORT_STORE (16-bit)
// ---------------------------------------------------------------------------
static void test_short_load_store() {
    auto cpu = run_program(
        addr_setup +
        "LDI #0xCD, R1\n"
        "LDI.S1 #0xAB, R1\n"       // R1 = 0xABCD
        "SHORT_STORE [R14], R1\n"
        "SHORT_LOAD  [R14], R2\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], 0xABCDULL, "SHORT_STORE+LOAD: round-trip");

    // Zero-extension
    cpu = run_program(
        addr_setup +
        "LDI64 #0xFFFFFFFFFFFFFFFF, R1\n"
        "SHORT_STORE [R14], R1\n"   // stores low 16 bits: 0xFFFF
        "SHORT_LOAD  [R14], R2\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], 0xFFFFULL, "SHORT_LOAD: zero-extended to 16 bits");
}

// ---------------------------------------------------------------------------
// WORD_LOAD / WORD_STORE (32-bit)
// ---------------------------------------------------------------------------
static void test_word_load_store() {
    auto cpu = run_program(
        addr_setup +
        "LDI    #0xEF, R1\n"
        "LDI.S1 #0xBE, R1\n"
        "LDI.S2 #0xAD, R1\n"
        "LDI.S3 #0xDE, R1\n"        // R1 = 0xDEADBEEF
        "WORD_STORE [R14], R1\n"
        "WORD_LOAD  [R14], R2\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], UINT64_C(0xDEADBEEF), "WORD_STORE+LOAD: round-trip");

    // Zero-extension: upper 32 bits must be 0
    cpu = run_program(
        addr_setup +
        "LDI64 #0xFFFFFFFFFFFFFFFF, R1\n"
        "WORD_STORE [R14], R1\n"    // stores low 32 bits: 0xFFFFFFFF
        "WORD_LOAD  [R14], R2\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], UINT64_C(0xFFFFFFFF), "WORD_LOAD: zero-extended");
}

// ---------------------------------------------------------------------------
// PUSH / POP (using R13 as stack pointer)
// ---------------------------------------------------------------------------
static void test_push_pop() {
    // Stack pointer starts at 0x2000 (well inside RAM)
    const std::string sp_setup =
        "LDI #0x00, R13\n"
        "LDI.S1 #0x20, R13\n";   // R13 = 0x2000

    // Push value, pop into different register
    auto cpu = run_program(
        sp_setup +
        "LDI #0xBB, R1\n"
        "PUSH R1, R13\n"         // SP decrements by 8, stores R1
        "POP  R2, R13\n"         // loads R2 from stack, SP increments by 8
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], 0xBBULL, "PUSH+POP: value preserved");
    CHECK_EQ(cpu.registers.regs[13], UINT64_C(0x2000), "PUSH+POP: SP restored");

    // SP changes correctly: -8 after PUSH, +8 after POP
    cpu = run_program(
        sp_setup +
        "LDI #1, R1\n"
        "PUSH R1, R13\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[13], UINT64_C(0x2000 - 8), "PUSH: SP decremented by 8");

    cpu = run_program(
        sp_setup +
        "LDI #1, R1\n"
        "PUSH R1, R13\n"
        "POP  R2, R13\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[13], UINT64_C(0x2000), "POP: SP incremented by 8");

    // LIFO ordering: push A, B; pop → B, A
    cpu = run_program(
        sp_setup +
        "LDI #0xAA, R1\n"
        "LDI #0xBB, R2\n"
        "PUSH R1, R13\n"       // stack: [AA]
        "PUSH R2, R13\n"       // stack: [AA, BB]
        "POP  R3, R13\n"       // R3 = BB (LIFO)
        "POP  R4, R13\n"       // R4 = AA
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[3], 0xBBULL, "PUSH/POP LIFO: first pop = BB");
    CHECK_EQ(cpu.registers.regs[4], 0xAAULL, "PUSH/POP LIFO: second pop = AA");
    CHECK_EQ(cpu.registers.regs[13], UINT64_C(0x2000), "PUSH/POP LIFO: SP restored");
}

// ---------------------------------------------------------------------------
// MOVE — address arithmetic (Format 0, no memory access)
// ---------------------------------------------------------------------------
static void test_move() {
    // MOVE R1, R2 → R2 = R1 + offset
    auto cpu = run_program(
        addr_setup +            // R14 = 0x1000
        "MOVE R14, R2\n"        // R2 = R14 + 0
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], UINT64_C(0x1000), "MOVE offset=0: R2=R14");

    cpu = run_program(
        addr_setup +
        "MOVE R14+2, R2\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], UINT64_C(0x1002), "MOVE offset=2");

    cpu = run_program(
        addr_setup +
        "MOVE R14+4, R2\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], UINT64_C(0x1004), "MOVE offset=4");

    cpu = run_program(
        addr_setup +
        "MOVE R14+6, R2\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], UINT64_C(0x1006), "MOVE offset=6");
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------
int main() {
    std::printf("=== Little-64 CPU memory instruction tests ===\n\n");
    std::printf("LOAD/STORE 64-bit\n");      test_load_store_64();
    std::printf("BYTE_LOAD/STORE\n");        test_byte_load_store();
    std::printf("SHORT_LOAD/STORE\n");       test_short_load_store();
    std::printf("WORD_LOAD/STORE\n");        test_word_load_store();
    std::printf("PUSH/POP\n");               test_push_pop();
    std::printf("MOVE\n");                   test_move();
    return print_summary();
}
