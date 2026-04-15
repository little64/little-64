#include "support/cpu_test_helpers.hpp"

static void run_gp_two_reg_case(const char* opcode_name,
                                int rs1,
                                uint64_t rs1_value,
                                int rd,
                                uint64_t rd_value,
                                uint64_t expected_rd,
                                uint64_t expected_flags,
                                const char* desc) {
    const auto result = exec2(encode_gp_rr(opcode_name, static_cast<uint8_t>(rs1), static_cast<uint8_t>(rd)),
                              rs1,
                              rs1_value,
                              rd,
                              rd_value);
    CHECK_EQ(result.rd_value, expected_rd, desc);
    CHECK_EQ(result.flags & (FLAG_Z | FLAG_C | FLAG_S), expected_flags, desc);
}

static void run_gp_imm_case(const char* opcode_name,
                            int imm4,
                            int rd,
                            uint64_t initial,
                            uint64_t expected_rd,
                            uint64_t expected_flags,
                            const char* desc) {
    const auto result = exec(encode_gp_imm(opcode_name, static_cast<uint8_t>(imm4), static_cast<uint8_t>(rd)),
                             rd,
                             initial);
    CHECK_EQ(result.rd_value, expected_rd, desc);
    CHECK_EQ(result.flags & (FLAG_Z | FLAG_C | FLAG_S), expected_flags, desc);
}

static void test_shared_gp_cases() {
#define LITTLE64_GP_TWO_REG_CASE(opcode_name, rs1, rs1_value, rd, rd_value, expected_rd, expected_flags, desc) \
    run_gp_two_reg_case(opcode_name, rs1, rs1_value, rd, rd_value, expected_rd, expected_flags, desc);
#define LITTLE64_GP_IMM_CASE(opcode_name, imm4, rd, initial, expected_rd, expected_flags, desc) \
    run_gp_imm_case(opcode_name, imm4, rd, initial, expected_rd, expected_flags, desc);
#include "shared/gp_alu_cases.def"
#undef LITTLE64_GP_TWO_REG_CASE
#undef LITTLE64_GP_IMM_CASE
}

// ---------------------------------------------------------------------------
// IMM-vs-register shift isolation
// ---------------------------------------------------------------------------
static void test_imm_vs_reg_shift() {
    Little64CPU cpu;
    cpu.registers.regs[1] = 1;   // value to shift
    cpu.registers.regs[2] = 5;   // register shift amount

    // SLLI #3 uses literal 3, not R2
    cpu.dispatchInstruction(make_instr("SLLI #3, R1"));
    CHECK_EQ(cpu.registers.regs[1], 1ULL << 3, "SLLI #3: uses literal, not R2");

    // SLL R2 uses R2=5
    cpu.registers.regs[1] = 1;
    cpu.dispatchInstruction(make_instr("SLL R2, R1"));
    CHECK_EQ(cpu.registers.regs[1], 1ULL << 5, "SLL R2: uses R2=5");
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------
int main() {
    std::printf("=== Little-64 CPU GP instruction tests ===\n\n");
    std::printf("shared GP ALU cases\n"); test_shared_gp_cases();
    std::printf("IMM vs REG isolation\n"); test_imm_vs_reg_shift();
    return print_summary();
}
