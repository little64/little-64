#include "support/cpu_test_helpers.hpp"

static void run_ldi_case(int shift,
                         int imm8,
                         int rd,
                         uint64_t initial,
                         uint64_t expected_rd,
                         uint64_t initial_flags,
                         uint64_t expected_flags,
                         const char* desc) {
    const auto result = exec(encode_ldi(static_cast<uint8_t>(shift), static_cast<uint8_t>(imm8), static_cast<uint8_t>(rd)),
                             rd,
                             initial,
                             initial_flags);
    CHECK_EQ(result.rd_value, expected_rd, desc);
    CHECK_EQ(result.flags & (FLAG_Z | FLAG_C | FLAG_S), expected_flags, desc);
}

static void test_shared_ldi_cases() {
#define LITTLE64_LDI_CASE(shift, imm8, rd, initial, expected_rd, initial_flags, expected_flags, desc) \
    run_ldi_case(shift, imm8, rd, initial, expected_rd, initial_flags, expected_flags, desc);
#include "shared/ldi_cases.def"
#undef LITTLE64_LDI_CASE
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
// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------
int main() {
    std::printf("=== Little-64 CPU LDI instruction tests ===\n\n");
    std::printf("shared LDI cases\n"); test_shared_ldi_cases();
    std::printf("LDI build 32-bit\n"); test_ldi_build32();
    std::printf("LDI64 pseudo\n");  test_ldi64();
    return print_summary();
}
