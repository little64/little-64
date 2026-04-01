#include "support/cpu_test_helpers.hpp"

// Integration tests: multi-instruction programs run via loadProgram + cycle().
// Tests exercise instruction interactions, call conventions, and data-in-memory patterns.

// ---------------------------------------------------------------------------
// Counter loop — count from 0 to N-1
// ---------------------------------------------------------------------------
static void test_counter_loop() {
    // R1 = counter, R2 = increment
    // Loop 10 times, then STOP. Verify R1 = 10.
    auto cpu = run_program(
        "LDI #0, R1\n"
        "LDI #1, R2\n"
        "LDI #10, R3\n"    // limit
        "loop:\n"
        "ADD R2, R1\n"     // R1++
        "SUB R2, R3\n"     // R3--
        "JUMP.Z @done\n"   // exit when R3 == 0
        "JUMP @loop\n"
        "done:\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[1], 10ULL, "counter loop: R1 = 10 after 10 iterations");
    CHECK_EQ(cpu.registers.regs[3], 0ULL,  "counter loop: R3 = 0 (limit exhausted)");
}

// ---------------------------------------------------------------------------
// Fibonacci — compute F(10) = 55
// ---------------------------------------------------------------------------
static void test_fibonacci() {
    // Iterative: R1 = F(n-2) = 0, R2 = F(n-1) = 1, R3 = counter
    // Each iteration: tmp = R2; R2 = R1 + R2; R1 = tmp; counter--
    auto cpu = run_program(
        "LDI #0, R1\n"      // F(0)
        "LDI #1, R2\n"      // F(1)
        "LDI #9, R3\n"      // need 9 more iterations to reach F(10)
        "LDI #1, R5\n"
        "iter:\n"
        "MOVE R2, R4\n"     // R4 = old F(n-1)
        "ADD R1, R2\n"      // R2 = F(n-1) + F(n-2) = F(n)
        "MOVE R4, R1\n"     // R1 = old F(n-1) = new F(n-2)
        "SUB R5, R3\n"      // R3--
        "JUMP.Z @fdone\n"
        "JUMP @iter\n"
        "fdone:\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], 55ULL, "Fibonacci: F(10) = 55");
}

// ---------------------------------------------------------------------------
// Stack round-trip — push 4 values, pop in LIFO order
// ---------------------------------------------------------------------------
static void test_stack_round_trip() {
    // Stack at 0x2000 in RAM
    auto cpu = run_program(
        "LDI #0x00, R13\n"
        "LDI.S1 #0x20, R13\n"    // SP = 0x2000
        "LDI #0x11, R1\n"
        "LDI #0x22, R2\n"
        "LDI #0x33, R3\n"
        "LDI #0x44, R4\n"
        "PUSH R1, R13\n"
        "PUSH R2, R13\n"
        "PUSH R3, R13\n"
        "PUSH R4, R13\n"
        "POP R8, R13\n"           // R8 = 0x44 (LIFO)
        "POP R7, R13\n"           // R7 = 0x33
        "POP R6, R13\n"           // R6 = 0x22
        "POP R5, R13\n"           // R5 = 0x11
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[5], 0x11ULL, "stack LIFO: R5 = 0x11");
    CHECK_EQ(cpu.registers.regs[6], 0x22ULL, "stack LIFO: R6 = 0x22");
    CHECK_EQ(cpu.registers.regs[7], 0x33ULL, "stack LIFO: R7 = 0x33");
    CHECK_EQ(cpu.registers.regs[8], 0x44ULL, "stack LIFO: R8 = 0x44");
    CHECK_EQ(cpu.registers.regs[13], UINT64_C(0x2000), "stack: SP restored");
}

// ---------------------------------------------------------------------------
// JAL leaf call — call a leaf function that adds 1 to R1, return via RET
// ---------------------------------------------------------------------------
static void test_jal_leaf_call() {
    auto cpu = run_program(
        "LDI #10, R1\n"
        "JAL @add_one\n"     // R14 = return address; jumps to add_one
        "STOP\n"
        "add_one:\n"
        "LDI #1, R2\n"
        "ADD R2, R1\n"       // R1++
        "RET\n"              // MOVE R14, R15 — return to caller
    );
    CHECK_EQ(cpu.registers.regs[1], 11ULL, "JAL: leaf add_one incremented R1");
}

// ---------------------------------------------------------------------------
// CALL/RET — two-level nested call; verifies LR saved and restored
// ---------------------------------------------------------------------------
static void test_call_nested() {
    // outer calls inner via CALL; inner increments R1 and returns;
    // outer adds 10 to R1 and returns; main verifies R1 = 11.
    auto cpu = run_program(
        "LDI #0, R1\n"
        "LDI #0x00, R13\n"
        "LDI.S1 #0x20, R13\n"    // SP = 0x2000
        "CALL @outer\n"
        "STOP\n"

        "outer:\n"
        "CALL @inner\n"           // saves R14 on stack; jumps to inner
        "LDI #10, R2\n"
        "ADD R2, R1\n"            // R1 += 10
        "RET\n"

        "inner:\n"
        "LDI #1, R2\n"
        "ADD R2, R1\n"            // R1 += 1
        "RET\n"
    );
    CHECK_EQ(cpu.registers.regs[1], 11ULL, "CALL/RET nested: R1 = 0 + 1 + 10 = 11");
}

// ---------------------------------------------------------------------------
// LDI64 — load arbitrary 64-bit immediate
// ---------------------------------------------------------------------------
static void test_ldi64_integration() {
    auto cpu = run_program(
        "LDI64 #0xDEADBEEFCAFEBABE, R1\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[1], UINT64_C(0xDEADBEEFCAFEBABE),
             "LDI64 integration: full 64-bit constant");

    // Two consecutive LDI64s to different registers
    cpu = run_program(
        "LDI64 #0x0102030405060708, R1\n"
        "LDI64 #0x090A0B0C0D0E0F10, R2\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[1], UINT64_C(0x0102030405060708), "LDI64 into R1");
    CHECK_EQ(cpu.registers.regs[2], UINT64_C(0x090A0B0C0D0E0F10), "LDI64 into R2");
}

// ---------------------------------------------------------------------------
// Little-endian memory layout — store individual bytes, read back as 64-bit
// ---------------------------------------------------------------------------
static void test_little_endian_layout() {
    // RAM base = 0x1000.  Write bytes 0x01, 0x02, 0x03 at offsets 0, 2, 4.
    // Then read the 64-bit word at 0x1000 and verify byte ordering.
    //
    // BYTE_STORE writes the low byte of the source register.
    // We write three separate bytes and check the 64-bit load sees them in
    // little-endian order: addr+0 is the least significant byte.
    auto cpu = run_program(
        "LDI #0x00, R14\n"
        "LDI.S1 #0x10, R14\n"    // R14 = 0x1000
        "LDI #0x01, R1\n"
        "BYTE_STORE [R14], R1\n"
        "LDI #0x02, R1\n"
        "BYTE_STORE [R14+2], R1\n"
        "LDI #0x03, R1\n"
        "BYTE_STORE [R14+4], R1\n"
        "LOAD [R14], R2\n"
        "STOP\n"
    );
    // Bytes at offsets 0, 1, 2, 3, 4, 5, 6, 7 of the 64-bit word:
    //   offset 0: 0x01, offset 1: 0x00 (uninitialised RAM), offset 2: 0x02,
    //   offset 3: 0x00, offset 4: 0x03, others 0x00
    // Little-endian 64-bit: byte[0] = LSB
    uint64_t expected = UINT64_C(0x01)
                      | (UINT64_C(0x02) << 16)
                      | (UINT64_C(0x03) << 32);
    CHECK_EQ(cpu.registers.regs[2], expected, "little-endian: bytes at expected positions");
}

// ---------------------------------------------------------------------------
// Memory copy — copy 4 words from source to destination using a loop
// ---------------------------------------------------------------------------
static void test_memory_copy() {
    // Copy a single 64-bit value via STORE+LOAD, verify at destination.
    // src = 0x1000, dst = 0x1040.
    auto cpu = run_program(
        "LDI #0x40, R11\n"
        "LDI.S1 #0x10, R11\n"    // R11 = dst = 0x1040
        "LDI #0x00, R10\n"
        "LDI.S1 #0x10, R10\n"    // R10 = src = 0x1000
        "LDI64 #0xABCDEF1234567890, R1\n"
        "STORE [R10], R1\n"
        "LOAD  [R10], R2\n"      // verify src
        "STORE [R11], R2\n"      // copy to dst
        "LOAD  [R11], R3\n"      // read dst
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[2], UINT64_C(0xABCDEF1234567890), "copy: src correct");
    CHECK_EQ(cpu.registers.regs[3], UINT64_C(0xABCDEF1234567890), "copy: dst matches src");
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------
int main() {
    std::printf("=== Little-64 CPU integration tests ===\n\n");
    std::printf("Counter loop\n");        test_counter_loop();
    std::printf("Fibonacci\n");           test_fibonacci();
    std::printf("Stack round-trip\n");    test_stack_round_trip();
    std::printf("JAL leaf call\n");       test_jal_leaf_call();
    std::printf("CALL/RET nested\n");     test_call_nested();
    std::printf("LDI64\n");              test_ldi64_integration();
    std::printf("Little-endian layout\n"); test_little_endian_layout();
    std::printf("Memory copy\n");         test_memory_copy();
    return print_summary();
}
