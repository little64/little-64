#include "test_harness.hpp"

// LDI — Load Immediate (Format 2)
//
// Encoding: bits[13:12] = shift (0-3), bits[11:4] = imm8, bits[3:0] = Rd
//   shift=0: Rd  = imm8          (replace entire register)
//   shift=1: Rd |= imm8 << 8     (OR into byte 1)
//   shift=2: Rd |= imm8 << 16    (OR into byte 2)
//   shift=3: Rd |= imm8 << 24    (OR into byte 3; sign-extends if imm8 bit 7 set)
//
// No flags are updated by LDI.

// ---------------------------------------------------------------------------
// shift = 0 — whole-register replace
// ---------------------------------------------------------------------------
static void test_ldi_shift0() {
    ExecResult r;

    r = exec("LDI #0, R1", 1, 0xFFFFFFFFFFFFFFFF);
    CHECK_EQ(r.rd_value, 0ULL,   "LDI #0: clears register");

    r = exec("LDI #1, R1", 1, 0xFFFF);
    CHECK_EQ(r.rd_value, 1ULL,   "LDI #1: replaces (not ORs) register");

    r = exec("LDI #255, R1", 1, 0);
    CHECK_EQ(r.rd_value, 255ULL, "LDI #255: max 8-bit value");

    r = exec("LDI #0x42, R1", 1, 0xDEAD);
    CHECK_EQ(r.rd_value, 0x42ULL, "LDI #0x42: replaces old value");
}

// ---------------------------------------------------------------------------
// shift = 1 — OR into bits[15:8]
// ---------------------------------------------------------------------------
static void test_ldi_shift1() {
    Little64CPU cpu;
    auto instr = make_instr("LDI.S1 #0xAB, R1");

    // From zero: bits[15:8] = 0xAB
    cpu.registers.regs[1] = 0;
    cpu.dispatchInstruction(instr);
    CHECK_EQ(cpu.registers.regs[1], UINT64_C(0xAB00), "LDI.S1: OR into byte 1");

    // Preserves low byte, sets byte 1
    cpu.registers.regs[1] = 0x55;
    cpu.dispatchInstruction(instr);
    CHECK_EQ(cpu.registers.regs[1], UINT64_C(0xAB55), "LDI.S1: preserves low byte");

    // OR semantics (doesn't clear existing bits in byte 1)
    cpu.registers.regs[1] = UINT64_C(0xFF00);
    cpu.dispatchInstruction(instr);
    CHECK_EQ(cpu.registers.regs[1], UINT64_C(0xFF00) | UINT64_C(0xAB00),
             "LDI.S1: OR (doesn't clear existing bits)");
}

// ---------------------------------------------------------------------------
// shift = 2 — OR into bits[23:16]
// ---------------------------------------------------------------------------
static void test_ldi_shift2() {
    Little64CPU cpu;
    auto instr = make_instr("LDI.S2 #0xCD, R1");

    cpu.registers.regs[1] = 0;
    cpu.dispatchInstruction(instr);
    CHECK_EQ(cpu.registers.regs[1], UINT64_C(0xCD0000), "LDI.S2: OR into byte 2");

    // Preserves lower two bytes
    cpu.registers.regs[1] = UINT64_C(0x1234);
    cpu.dispatchInstruction(instr);
    CHECK_EQ(cpu.registers.regs[1], UINT64_C(0xCD1234), "LDI.S2: preserves low 2 bytes");
}

// ---------------------------------------------------------------------------
// shift = 3 — OR into bits[31:24]; sign-extend if imm8 bit 7 set
// ---------------------------------------------------------------------------
static void test_ldi_shift3() {
    Little64CPU cpu;

    // Positive imm (MSB clear): no sign extension
    auto instr_pos = make_instr("LDI.S3 #0x7F, R1");
    cpu.registers.regs[1] = 0;
    cpu.dispatchInstruction(instr_pos);
    CHECK_EQ(cpu.registers.regs[1], UINT64_C(0x7F000000),
             "LDI.S3 positive: no sign extension");

    // Negative imm (MSB set): sign-extends bits[63:24] to all 1s
    auto instr_neg = make_instr("LDI.S3 #0x80, R1");
    cpu.registers.regs[1] = 0;
    cpu.dispatchInstruction(instr_neg);
    // 0x80 << 24 = 0x80000000; OR 0xFFFFFFFFFFFFFF00 → 0xFFFFFFFF80000000
    CHECK_EQ(cpu.registers.regs[1], UINT64_C(0xFFFFFFFF80000000),
             "LDI.S3 MSB set: sign extends to upper 40 bits");

    // Sign extension with other bits already in low bytes
    cpu.registers.regs[1] = UINT64_C(0x1234);
    cpu.dispatchInstruction(instr_neg);
    CHECK_EQ(cpu.registers.regs[1], UINT64_C(0xFFFFFFFF80001234),
             "LDI.S3 sign-ext: preserves low bytes");

    // Another negative value: 0xFF
    auto instr_ff = make_instr("LDI.S3 #0xFF, R1");
    cpu.registers.regs[1] = 0;
    cpu.dispatchInstruction(instr_ff);
    CHECK_EQ(cpu.registers.regs[1], UINT64_C(0xFFFFFFFFFF000000),
             "LDI.S3 #0xFF: fully extends");
}

// ---------------------------------------------------------------------------
// Building a 32-bit value with four LDI instructions (via run_program)
// ---------------------------------------------------------------------------
static void test_ldi_build32() {
    // Build 0x12345678: byte 0=0x78, byte 1=0x56, byte 2=0x34, byte 3=0x12
    // 0x12 has bit 7 clear — no sign extension.
    auto cpu = run_program(
        "LDI    #0x78, R1\n"
        "LDI.S1 #0x56, R1\n"
        "LDI.S2 #0x34, R1\n"
        "LDI.S3 #0x12, R1\n"   // 0x12: bit 7 clear, no sign ext
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[1], UINT64_C(0x12345678), "LDI build 0x12345678");
}

// ---------------------------------------------------------------------------
// LDI64 pseudo-instruction — loads a full 64-bit immediate via run_program
// ---------------------------------------------------------------------------
static void test_ldi64() {
    auto cpu = run_program("LDI64 #0xDEADBEEFCAFEBABE, R1\nSTOP\n");
    CHECK_EQ(cpu.registers.regs[1], UINT64_C(0xDEADBEEFCAFEBABE),
             "LDI64: arbitrary 64-bit value");

    cpu = run_program("LDI64 #0, R1\nSTOP\n");
    CHECK_EQ(cpu.registers.regs[1], 0ULL, "LDI64 #0");

    cpu = run_program("LDI64 #0xFFFFFFFFFFFFFFFF, R1\nSTOP\n");
    CHECK_EQ(cpu.registers.regs[1], UINT64_MAX, "LDI64 UINT64_MAX");

    // Different destination register
    cpu = run_program("LDI64 #0x123456789ABCDEF0, R5\nSTOP\n");
    CHECK_EQ(cpu.registers.regs[5], UINT64_C(0x123456789ABCDEF0),
             "LDI64: different destination register");
}

// ---------------------------------------------------------------------------
// LDI does NOT update flags
// ---------------------------------------------------------------------------
static void test_ldi_no_flags() {
    // Set known flags via SUB that produces a non-zero result (no flags set normally)
    // Then run LDI; flags must remain whatever they were.
    auto cpu = run_program(
        "LDI #5, R1\n"
        "LDI #3, R2\n"
        "SUB R2, R1\n"   // R1 = 2; Z=0 C=0 S=0
        "LDI #0, R3\n"   // LDI on R3; must NOT clear or change flags
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.flags & FLAG_Z, 0ULL, "LDI does not set Z");
    CHECK_EQ(cpu.registers.flags & FLAG_C, 0ULL, "LDI does not set C");
    CHECK_EQ(cpu.registers.flags & FLAG_S, 0ULL, "LDI does not set S");

    // With carry flag set before LDI
    cpu = run_program(
        "LDI #3, R1\n"
        "LDI #5, R2\n"
        "SUB R2, R1\n"   // R1 = -2 as uint64; C=1 (borrow)
        "LDI #42, R3\n"  // LDI must not clear carry
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.flags & FLAG_C, FLAG_C, "LDI does not clear carry flag");
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------
int main() {
    std::printf("=== Little-64 CPU LDI instruction tests ===\n\n");
    std::printf("LDI shift=0\n");   test_ldi_shift0();
    std::printf("LDI shift=1\n");   test_ldi_shift1();
    std::printf("LDI shift=2\n");   test_ldi_shift2();
    std::printf("LDI shift=3\n");   test_ldi_shift3();
    std::printf("LDI build 32-bit\n"); test_ldi_build32();
    std::printf("LDI64 pseudo\n");  test_ldi64();
    std::printf("LDI no flags\n");  test_ldi_no_flags();
    return print_summary();
}
