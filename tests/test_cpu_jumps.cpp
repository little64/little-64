#include "test_harness.hpp"

// Conditional and unconditional jumps.
//
// All tests use run_program(). The standard pattern:
//   1. Execute an instruction that sets known flags.
//   2. Conditional jump over one of two outcome blocks.
//   3. "Taken" block stores 1 in R1; "not taken" block stores 2 in R1.
//   4. Both paths converge at STOP.
//   5. Verify R1.
//
// Labels are used for readability; the assembler resolves them.

// ---------------------------------------------------------------------------
// Helper: assemble a jump test and return R1 (1=taken, 2=not taken)
// ---------------------------------------------------------------------------
static uint64_t jump_result(const std::string& src) {
    auto cpu = run_program(src);
    return cpu.registers.regs[1];
}

// ---------------------------------------------------------------------------
// JUMP.Z — taken when Z=1 (result was zero)
// ---------------------------------------------------------------------------
static void test_jump_z() {
    // Taken: SUB equal operands → Z=1
    CHECK_EQ(jump_result(
        "LDI #5, R2\n"
        "LDI #5, R3\n"
        "SUB R3, R2\n"          // R2 = 0, Z=1
        "JUMP.Z @taken\n"
        "LDI #2, R1\n"          // not-taken path
        "JUMP @end\n"
        "taken:\n"
        "LDI #1, R1\n"          // taken path
        "end:\n"
        "STOP\n"
    ), 1ULL, "JUMP.Z taken when Z=1");

    // Not taken: non-zero result → Z=0
    CHECK_EQ(jump_result(
        "LDI #5, R2\n"
        "LDI #3, R3\n"
        "SUB R3, R2\n"          // R2 = 2, Z=0
        "JUMP.Z @taken\n"
        "LDI #2, R1\n"
        "JUMP @end\n"
        "taken:\n"
        "LDI #1, R1\n"
        "end:\n"
        "STOP\n"
    ), 2ULL, "JUMP.Z not taken when Z=0");
}

// ---------------------------------------------------------------------------
// JUMP.C — taken when C=1 (carry / borrow set)
// ---------------------------------------------------------------------------
static void test_jump_c() {
    // Taken: borrow — Rs1 > Rd in SUB → C=1
    CHECK_EQ(jump_result(
        "LDI #3, R2\n"
        "LDI #5, R3\n"
        "SUB R3, R2\n"          // 3 - 5: borrow → C=1
        "JUMP.C @taken\n"
        "LDI #2, R1\n"
        "JUMP @end\n"
        "taken:\n"
        "LDI #1, R1\n"
        "end:\n"
        "STOP\n"
    ), 1ULL, "JUMP.C taken when C=1 (borrow)");

    // Not taken: no borrow
    CHECK_EQ(jump_result(
        "LDI #5, R2\n"
        "LDI #3, R3\n"
        "SUB R3, R2\n"          // 5 - 3: no borrow → C=0
        "JUMP.C @taken\n"
        "LDI #2, R1\n"
        "JUMP @end\n"
        "taken:\n"
        "LDI #1, R1\n"
        "end:\n"
        "STOP\n"
    ), 2ULL, "JUMP.C not taken when C=0");

    // Taken: carry from ADD overflow
    CHECK_EQ(jump_result(
        "LDI64 #0xFFFFFFFFFFFFFFFF, R2\n"
        "LDI #1, R3\n"
        "ADD R3, R2\n"          // overflow → C=1
        "JUMP.C @taken\n"
        "LDI #2, R1\n"
        "JUMP @end\n"
        "taken:\n"
        "LDI #1, R1\n"
        "end:\n"
        "STOP\n"
    ), 1ULL, "JUMP.C taken on ADD overflow");
}

// ---------------------------------------------------------------------------
// JUMP.S — taken when S=1 (sign flag, bit 63 of result set)
// ---------------------------------------------------------------------------
static void test_jump_s() {
    // Taken: result has bit 63 set (0 - 1 = UINT64_MAX via wrap)
    CHECK_EQ(jump_result(
        "LDI #0, R2\n"
        "LDI #1, R3\n"
        "SUB R3, R2\n"          // 0 - 1 = UINT64_MAX → S=1
        "JUMP.S @taken\n"
        "LDI #2, R1\n"
        "JUMP @end\n"
        "taken:\n"
        "LDI #1, R1\n"
        "end:\n"
        "STOP\n"
    ), 1ULL, "JUMP.S taken when S=1");

    // Not taken: positive result
    CHECK_EQ(jump_result(
        "LDI #5, R2\n"
        "LDI #3, R3\n"
        "SUB R3, R2\n"          // 5 - 3 = 2 → S=0
        "JUMP.S @taken\n"
        "LDI #2, R1\n"
        "JUMP @end\n"
        "taken:\n"
        "LDI #1, R1\n"
        "end:\n"
        "STOP\n"
    ), 2ULL, "JUMP.S not taken when S=0");
}

// ---------------------------------------------------------------------------
// JUMP.GT — taken when Z=0 AND S=0 (strictly positive)
// ---------------------------------------------------------------------------
static void test_jump_gt() {
    // Taken: positive result (Z=0, S=0)
    CHECK_EQ(jump_result(
        "LDI #5, R2\n"
        "LDI #3, R3\n"
        "SUB R3, R2\n"          // 2 → Z=0 S=0
        "JUMP.GT @taken\n"
        "LDI #2, R1\n"
        "JUMP @end\n"
        "taken:\n"
        "LDI #1, R1\n"
        "end:\n"
        "STOP\n"
    ), 1ULL, "JUMP.GT taken on positive result");

    // Not taken: zero result (Z=1)
    CHECK_EQ(jump_result(
        "LDI #5, R2\n"
        "LDI #5, R3\n"
        "SUB R3, R2\n"          // 0 → Z=1
        "JUMP.GT @taken\n"
        "LDI #2, R1\n"
        "JUMP @end\n"
        "taken:\n"
        "LDI #1, R1\n"
        "end:\n"
        "STOP\n"
    ), 2ULL, "JUMP.GT not taken on zero");

    // Not taken: sign set (S=1)
    CHECK_EQ(jump_result(
        "LDI #0, R2\n"
        "LDI #1, R3\n"
        "SUB R3, R2\n"          // wraps → S=1
        "JUMP.GT @taken\n"
        "LDI #2, R1\n"
        "JUMP @end\n"
        "taken:\n"
        "LDI #1, R1\n"
        "end:\n"
        "STOP\n"
    ), 2ULL, "JUMP.GT not taken when S=1");
}

// ---------------------------------------------------------------------------
// JUMP.LT — taken when S=1 (same condition as JUMP.S)
// ---------------------------------------------------------------------------
static void test_jump_lt() {
    // Taken: sign set
    CHECK_EQ(jump_result(
        "LDI #0, R2\n"
        "LDI #1, R3\n"
        "SUB R3, R2\n"
        "JUMP.LT @taken\n"
        "LDI #2, R1\n"
        "JUMP @end\n"
        "taken:\n"
        "LDI #1, R1\n"
        "end:\n"
        "STOP\n"
    ), 1ULL, "JUMP.LT taken when S=1");

    // Not taken: positive result (S=0, Z=0)
    CHECK_EQ(jump_result(
        "LDI #7, R2\n"
        "LDI #3, R3\n"
        "SUB R3, R2\n"          // 4 → S=0
        "JUMP.LT @taken\n"
        "LDI #2, R1\n"
        "JUMP @end\n"
        "taken:\n"
        "LDI #1, R1\n"
        "end:\n"
        "STOP\n"
    ), 2ULL, "JUMP.LT not taken when S=0");

    // Not taken: zero result (S=0)
    CHECK_EQ(jump_result(
        "LDI #4, R2\n"
        "LDI #4, R3\n"
        "SUB R3, R2\n"          // 0 → Z=1 S=0
        "JUMP.LT @taken\n"
        "LDI #2, R1\n"
        "JUMP @end\n"
        "taken:\n"
        "LDI #1, R1\n"
        "end:\n"
        "STOP\n"
    ), 2ULL, "JUMP.LT not taken when Z=1, S=0");
}

// ---------------------------------------------------------------------------
// Unconditional JUMP (pseudo → MOVE R15, R15-relative)
// ---------------------------------------------------------------------------
static void test_jump_unconditional() {
    // Jump over an instruction that would set R1 to 2
    CHECK_EQ(jump_result(
        "JUMP @skip\n"
        "LDI #2, R1\n"          // skipped
        "skip:\n"
        "LDI #1, R1\n"
        "STOP\n"
    ), 1ULL, "JUMP unconditional: skips over instruction");
}

// ---------------------------------------------------------------------------
// Backward jump — loop: count down from 5, verify 5 iterations
// ---------------------------------------------------------------------------
static void test_backward_loop() {
    auto cpu = run_program(
        "LDI #5, R1\n"          // R1 = loop counter (counts down)
        "LDI #0, R2\n"          // R2 = iteration count (counts up)
        "loop:\n"
        "LDI #1, R3\n"
        "ADD R3, R2\n"          // R2++
        "SUB R3, R1\n"          // R1--; sets Z when R1 reaches 0
        "JUMP.Z @done\n"        // exit when R1 == 0
        "JUMP @loop\n"          // keep looping while R1 != 0
        "done:\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[1], 0ULL,  "loop: counter reaches 0");
    CHECK_EQ(cpu.registers.regs[2], 5ULL,  "loop: executed 5 iterations");
}

// ---------------------------------------------------------------------------
// Forward jump — skip an instruction, verify register unchanged
// ---------------------------------------------------------------------------
static void test_forward_skip() {
    auto cpu = run_program(
        "LDI #42, R1\n"
        "JUMP @skip\n"
        "LDI #99, R1\n"         // must not execute
        "skip:\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[1], 42ULL, "forward skip: R1 unchanged");
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------
int main() {
    std::printf("=== Little-64 CPU jump instruction tests ===\n\n");
    std::printf("JUMP.Z\n");  test_jump_z();
    std::printf("JUMP.C\n");  test_jump_c();
    std::printf("JUMP.S\n");  test_jump_s();
    std::printf("JUMP.GT\n"); test_jump_gt();
    std::printf("JUMP.LT\n"); test_jump_lt();
    std::printf("JUMP (unconditional)\n"); test_jump_unconditional();
    std::printf("Backward loop\n"); test_backward_loop();
    std::printf("Forward skip\n");  test_forward_skip();
    return print_summary();
}
