#include "support/cpu_test_helpers.hpp"
static void run_program_regs_case(const char* description,
                                  const char* source,
                                  int reg_a,
                                  uint64_t value_a,
                                  int reg_b,
                                  uint64_t value_b,
                                  int reg_c,
                                  uint64_t value_c) {
    auto cpu = run_program(source);
    if (reg_a >= 0) CHECK_EQ(cpu.registers.regs[reg_a], value_a, description);
    if (reg_b >= 0) CHECK_EQ(cpu.registers.regs[reg_b], value_b, description);
    if (reg_c >= 0) CHECK_EQ(cpu.registers.regs[reg_c], value_c, description);
}

static void test_shared_jump_program_cases() {
#define LITTLE64_PROGRAM_REGS_CASE(description, source, reg_a, value_a, reg_b, value_b, reg_c, value_c) \
    run_program_regs_case(description, source, reg_a, value_a, reg_b, value_b, reg_c, value_c);
#include "shared/jump_program_cases.def"
#undef LITTLE64_PROGRAM_REGS_CASE
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------
int main() {
    std::printf("=== Little-64 CPU jump instruction tests ===\n\n");
    std::printf("shared jump programs\n"); test_shared_jump_program_cases();
    return print_summary();
}
