#include "test_harness.hpp"

// GP ALU instructions: ADD, SUB, TEST, AND, OR, XOR,
//                      SLL, SRL, SRA  (register shift amount),
//                      SLLI, SRLI, SRAI (4-bit immediate shift amount)
//
// All tests use dispatchInstruction — no memory access needed.
// For RS1_RD instructions the test sets both Rs1 and Rd directly on the CPU.

// ---------------------------------------------------------------------------
// Helper: execute a two-register GP instruction (RS1_RD encoding).
// Returns ExecResult for Rd after dispatch.
// ---------------------------------------------------------------------------
struct TwoRegResult {
    uint64_t rd_value;
    uint64_t flags;
};
static TwoRegResult exec2(const char* src, int rs1, uint64_t b, int rd, uint64_t a) {
    Little64CPU cpu;
    cpu.registers.regs[rs1] = b;
    cpu.registers.regs[rd]  = a;
    cpu.dispatchInstruction(make_instr(src));
    return { cpu.registers.regs[rd], cpu.registers.flags };
}

// ---------------------------------------------------------------------------
// ADD
// ---------------------------------------------------------------------------
static void test_add() {
    TwoRegResult r;

    // Basic: 3 + 4 = 7, no flags
    r = exec2("ADD R1, R2", 1, 3, 2, 4);
    CHECK_EQ(r.rd_value, 7ULL,         "ADD 3+4=7");
    CHECK_EQ(r.flags & FLAG_Z, 0ULL,   "ADD: Z=0");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "ADD: C=0");
    CHECK_EQ(r.flags & FLAG_S, 0ULL,   "ADD: S=0");

    // Zero result
    r = exec2("ADD R1, R2", 1, 0, 2, 0);
    CHECK_EQ(r.rd_value, 0ULL,         "ADD 0+0=0");
    CHECK_EQ(r.flags & FLAG_Z, FLAG_Z, "ADD: Z=1 on zero");

    // Sign flag: bit 63 set
    r = exec2("ADD R1, R2", 1, 0, 2, UINT64_C(1) << 63);
    CHECK_EQ(r.flags & FLAG_S, FLAG_S, "ADD: S=1 when bit 63 set");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "ADD: C=0 (no wrap)");

    // Carry (unsigned overflow): UINT64_MAX + 1 = 0
    r = exec2("ADD R1, R2", 1, 1, 2, UINT64_MAX);
    CHECK_EQ(r.rd_value, 0ULL,         "ADD UINT64_MAX+1 wraps to 0");
    CHECK_EQ(r.flags & FLAG_Z, FLAG_Z, "ADD wrap: Z=1");
    CHECK_EQ(r.flags & FLAG_C, FLAG_C, "ADD wrap: C=1");

    // Carry but non-zero result
    r = exec2("ADD R1, R2", 1, 2, 2, UINT64_MAX);
    CHECK_EQ(r.rd_value, 1ULL,         "ADD UINT64_MAX+2=1");
    CHECK_EQ(r.flags & FLAG_C, FLAG_C, "ADD wrap+1: C=1");
    CHECK_EQ(r.flags & FLAG_Z, 0ULL,   "ADD wrap+1: Z=0");
}

// ---------------------------------------------------------------------------
// SUB
// ---------------------------------------------------------------------------
static void test_sub() {
    TwoRegResult r;

    // Basic: 7 - 3 = 4
    r = exec2("SUB R1, R2", 1, 3, 2, 7);
    CHECK_EQ(r.rd_value, 4ULL,         "SUB 7-3=4");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "SUB: C=0 (no borrow)");
    CHECK_EQ(r.flags & FLAG_Z, 0ULL,   "SUB: Z=0");

    // Zero result
    r = exec2("SUB R1, R2", 1, 5, 2, 5);
    CHECK_EQ(r.rd_value, 0ULL,         "SUB 5-5=0");
    CHECK_EQ(r.flags & FLAG_Z, FLAG_Z, "SUB: Z=1");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "SUB: C=0 (equal, no borrow)");

    // Borrow: b > a (C set when Rs1 > Rd)
    r = exec2("SUB R1, R2", 1, 5, 2, 3);
    CHECK_EQ(r.flags & FLAG_C, FLAG_C, "SUB: C=1 when Rs1>Rd (borrow)");

    // No borrow: a >= b
    r = exec2("SUB R1, R2", 1, 3, 2, 5);
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "SUB: C=0 when Rd>=Rs1");

    // Sign flag: result has bit 63 set (e.g. 0 - 1 = UINT64_MAX)
    r = exec2("SUB R1, R2", 1, 1, 2, 0);
    CHECK_EQ(r.flags & FLAG_S, FLAG_S, "SUB: S=1 on wraparound result");
    CHECK_EQ(r.flags & FLAG_C, FLAG_C, "SUB: C=1 on wraparound");
}

// ---------------------------------------------------------------------------
// TEST (same flag semantics as SUB, but Rd not written)
// ---------------------------------------------------------------------------
static void test_test() {
    TwoRegResult r;

    // Equal operands: Z=1, C=0
    r = exec2("TEST R1, R2", 1, 7, 2, 7);
    CHECK_EQ(r.flags & FLAG_Z, FLAG_Z, "TEST equal: Z=1");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "TEST equal: C=0");
    CHECK_EQ(r.rd_value, 7ULL,         "TEST: Rd unchanged");

    // Rd > Rs1: C=0, Z=0
    r = exec2("TEST R1, R2", 1, 3, 2, 7);
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "TEST Rd>Rs1: C=0");
    CHECK_EQ(r.flags & FLAG_Z, 0ULL,   "TEST Rd>Rs1: Z=0");
    CHECK_EQ(r.rd_value, 7ULL,         "TEST: Rd unchanged (Rd>Rs1)");

    // Rd < Rs1: borrow → C=1
    r = exec2("TEST R1, R2", 1, 7, 2, 3);
    CHECK_EQ(r.flags & FLAG_C, FLAG_C, "TEST Rd<Rs1: C=1 (borrow)");
    CHECK_EQ(r.rd_value, 3ULL,         "TEST: Rd unchanged (Rd<Rs1)");
}

// ---------------------------------------------------------------------------
// AND
// ---------------------------------------------------------------------------
static void test_and() {
    TwoRegResult r;

    // Mask: keep only low 4 bits
    r = exec2("AND R1, R2", 1, 0xF, 2, 0xFF);
    CHECK_EQ(r.rd_value, 0xFULL,       "AND mask low 4 bits");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "AND: C always 0");

    // Zero result
    r = exec2("AND R1, R2", 1, 0xF0, 2, 0x0F);
    CHECK_EQ(r.rd_value, 0ULL,         "AND no common bits → 0");
    CHECK_EQ(r.flags & FLAG_Z, FLAG_Z, "AND zero: Z=1");

    // Identity: AND with UINT64_MAX
    r = exec2("AND R1, R2", 1, UINT64_MAX, 2, 0xABCD);
    CHECK_EQ(r.rd_value, 0xABCDULL,    "AND UINT64_MAX = identity");

    // Sign flag
    r = exec2("AND R1, R2", 1, UINT64_MAX, 2, UINT64_C(1) << 63);
    CHECK_EQ(r.flags & FLAG_S, FLAG_S, "AND: S=1 when bit 63 set in result");
}

// ---------------------------------------------------------------------------
// OR
// ---------------------------------------------------------------------------
static void test_or() {
    TwoRegResult r;

    // Combine disjoint bits
    r = exec2("OR R1, R2", 1, 0xF0, 2, 0x0F);
    CHECK_EQ(r.rd_value, 0xFFULL,      "OR combine disjoint bits");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "OR: C always 0");

    // Zero OR zero = zero
    r = exec2("OR R1, R2", 1, 0, 2, 0);
    CHECK_EQ(r.rd_value, 0ULL,         "OR 0|0=0");
    CHECK_EQ(r.flags & FLAG_Z, FLAG_Z, "OR zero: Z=1");

    // Sign flag
    r = exec2("OR R1, R2", 1, UINT64_C(1) << 63, 2, 0);
    CHECK_EQ(r.flags & FLAG_S, FLAG_S, "OR: S=1 when bit 63 set");
}

// ---------------------------------------------------------------------------
// XOR
// ---------------------------------------------------------------------------
static void test_xor() {
    TwoRegResult r;

    // Toggle bits
    r = exec2("XOR R1, R2", 1, 0xF0, 2, 0xFF);
    CHECK_EQ(r.rd_value, 0x0FULL,      "XOR toggle");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "XOR: C always 0");

    // Self-cancel: a XOR a = 0
    r = exec2("XOR R1, R2", 1, 0xDEAD, 2, 0xDEAD);
    CHECK_EQ(r.rd_value, 0ULL,         "XOR self-cancel = 0");
    CHECK_EQ(r.flags & FLAG_Z, FLAG_Z, "XOR self: Z=1");

    // Sign flag
    r = exec2("XOR R1, R2", 1, 0, 2, UINT64_C(1) << 63);
    CHECK_EQ(r.flags & FLAG_S, FLAG_S, "XOR: S=1 when bit 63 set");
}

// ---------------------------------------------------------------------------
// SLL — Shift Left Logical (register shift amount)
// ---------------------------------------------------------------------------
static void test_sll() {
    TwoRegResult r;

    // Shift by 0: unchanged, flags on original
    r = exec2("SLL R1, R2", 1, 0, 2, 42);
    CHECK_EQ(r.rd_value, 42ULL,        "SLL #0: unchanged");
    CHECK_EQ(r.flags & FLAG_Z, 0ULL,   "SLL #0: Z=0");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "SLL #0: C=0");

    // Basic shift
    r = exec2("SLL R1, R2", 1, 1, 2, 1);
    CHECK_EQ(r.rd_value, 2ULL,         "SLL 1<<1=2");

    // Shift by 63
    r = exec2("SLL R1, R2", 1, 63, 2, 1);
    CHECK_EQ(r.rd_value, UINT64_C(1) << 63, "SLL 1<<63");
    CHECK_EQ(r.flags & FLAG_S, FLAG_S,      "SLL 1<<63: S=1");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,        "SLL 1<<63: C=0");

    // Carry: MSB shifted out
    r = exec2("SLL R1, R2", 1, 1, 2, UINT64_C(1) << 63);
    CHECK_EQ(r.rd_value, 0ULL,         "SLL MSB<<1=0");
    CHECK_EQ(r.flags & FLAG_C, FLAG_C, "SLL MSB<<1: C=1");
    CHECK_EQ(r.flags & FLAG_Z, FLAG_Z, "SLL MSB<<1: Z=1");

    // Shift by ≥64: result = 0
    r = exec2("SLL R1, R2", 1, 64, 2, UINT64_MAX);
    CHECK_EQ(r.rd_value, 0ULL,         "SLL shift≥64: result=0");
    CHECK_EQ(r.flags & FLAG_Z, FLAG_Z, "SLL shift≥64: Z=1");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "SLL shift≥64: C=0");

    r = exec2("SLL R1, R2", 1, 65, 2, 1);
    CHECK_EQ(r.rd_value, 0ULL,         "SLL shift=65: result=0");
}

// ---------------------------------------------------------------------------
// SRL — Shift Right Logical (register shift amount)
// ---------------------------------------------------------------------------
static void test_srl() {
    TwoRegResult r;

    // Shift by 0: unchanged
    r = exec2("SRL R1, R2", 1, 0, 2, 0xABCD);
    CHECK_EQ(r.rd_value, 0xABCDULL,    "SRL #0: unchanged");

    // Basic shift
    r = exec2("SRL R1, R2", 1, 1, 2, 4);
    CHECK_EQ(r.rd_value, 2ULL,         "SRL 4>>1=2");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "SRL 4>>1: C=0 (bit 0 was 0)");

    // Carry: bit 0 shifted out
    r = exec2("SRL R1, R2", 1, 1, 2, 1);
    CHECK_EQ(r.rd_value, 0ULL,         "SRL 1>>1=0");
    CHECK_EQ(r.flags & FLAG_C, FLAG_C, "SRL 1>>1: C=1");
    CHECK_EQ(r.flags & FLAG_Z, FLAG_Z, "SRL 1>>1: Z=1");

    // Logical: MSB not extended
    r = exec2("SRL R1, R2", 1, 1, 2, UINT64_C(1) << 63);
    CHECK_EQ(r.rd_value, UINT64_C(1) << 62, "SRL logical: no sign extend");
    CHECK_EQ(r.flags & FLAG_S, 0ULL,        "SRL: S=0 after logical shift");

    // Shift by 63
    r = exec2("SRL R1, R2", 1, 63, 2, UINT64_C(1) << 63);
    CHECK_EQ(r.rd_value, 1ULL,         "SRL MSB>>63=1");

    // Shift by ≥64: result = 0
    r = exec2("SRL R1, R2", 1, 64, 2, UINT64_MAX);
    CHECK_EQ(r.rd_value, 0ULL,         "SRL shift≥64: result=0");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "SRL shift≥64: C=0");
}

// ---------------------------------------------------------------------------
// SRA — Shift Right Arithmetic (register shift amount)
// ---------------------------------------------------------------------------
static void test_sra() {
    TwoRegResult r;

    // Shift by 0: unchanged
    r = exec2("SRA R1, R2", 1, 0, 2, 42);
    CHECK_EQ(r.rd_value, 42ULL,        "SRA #0: unchanged");

    // Positive input: same as SRL
    r = exec2("SRA R1, R2", 1, 1, 2, 4);
    CHECK_EQ(r.rd_value, 2ULL,         "SRA positive: 4>>1=2");

    // Carry flag
    r = exec2("SRA R1, R2", 1, 1, 2, 1);
    CHECK_EQ(r.rd_value, 0ULL,         "SRA 1>>1=0");
    CHECK_EQ(r.flags & FLAG_C, FLAG_C, "SRA 1>>1: C=1 (bit 0 was 1)");

    // Arithmetic: sign extends for negative input
    r = exec2("SRA R1, R2", 1, 1, 2, UINT64_C(1) << 63);
    CHECK_EQ(r.rd_value, UINT64_C(3) << 62, "SRA MSB>>1: sign extends to 0xC0...");
    CHECK_EQ(r.flags & FLAG_S, FLAG_S,      "SRA: S=1 (still negative)");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,        "SRA MSB>>1: C=0 (bit 0 was 0)");

    // Shift by 63: all sign bits fill
    r = exec2("SRA R1, R2", 1, 63, 2, UINT64_C(1) << 63);
    CHECK_EQ(r.rd_value, UINT64_MAX,   "SRA negative>>63=UINT64_MAX");

    // Shift ≥64, negative: UINT64_MAX
    r = exec2("SRA R1, R2", 1, 64, 2, UINT64_C(1) << 63);
    CHECK_EQ(r.rd_value, UINT64_MAX,   "SRA negative, shift≥64 = UINT64_MAX");

    // Shift ≥64, positive: 0
    r = exec2("SRA R1, R2", 1, 64, 2, 1);
    CHECK_EQ(r.rd_value, 0ULL,         "SRA positive, shift≥64 = 0");
}

// ---------------------------------------------------------------------------
// SLLI, SRLI, SRAI — immediate shift amount (4-bit, 0–15)
// Tests use exec() since only one register (Rd) is involved.
// ---------------------------------------------------------------------------

static void test_slli() {
    ExecResult r;

    r = exec("SLLI #0, R1", 1, 42);
    CHECK_EQ(r.rd_value, 42ULL,        "SLLI #0: unchanged");
    CHECK_EQ(r.flags & FLAG_Z, 0ULL,   "SLLI #0: Z=0");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "SLLI #0: C=0");

    r = exec("SLLI #0, R1", 1, 0);
    CHECK_EQ(r.flags & FLAG_Z, FLAG_Z, "SLLI #0 on 0: Z=1");

    r = exec("SLLI #1, R1", 1, 1);
    CHECK_EQ(r.rd_value, 2ULL,         "SLLI #1: 1<<1=2");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "SLLI #1: C=0");

    r = exec("SLLI #15, R1", 1, 1);
    CHECK_EQ(r.rd_value, 1ULL << 15,   "SLLI #15: 1<<15");

    // Sign flag: result has bit 63 set
    r = exec("SLLI #1, R1", 1, UINT64_C(1) << 62);
    CHECK_EQ(r.rd_value, UINT64_C(1) << 63, "SLLI #1: result has bit 63");
    CHECK_EQ(r.flags & FLAG_S, FLAG_S,      "SLLI #1: S=1");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,        "SLLI #1: C=0 (bit 63 of input was 0)");

    // Carry: MSB shifted out
    r = exec("SLLI #1, R1", 1, UINT64_C(1) << 63);
    CHECK_EQ(r.rd_value, 0ULL,         "SLLI #1 from MSB: result=0");
    CHECK_EQ(r.flags & FLAG_Z, FLAG_Z, "SLLI #1 from MSB: Z=1");
    CHECK_EQ(r.flags & FLAG_C, FLAG_C, "SLLI #1 from MSB: C=1");

    // Multi-bit carry
    r = exec("SLLI #4, R1", 1, UINT64_C(0xF0) << 56);
    CHECK_EQ(r.rd_value, 0ULL,         "SLLI #4: all bits shifted out");
    CHECK_EQ(r.flags & FLAG_C, FLAG_C, "SLLI #4: C=1");
}

static void test_srli() {
    ExecResult r;

    r = exec("SRLI #0, R1", 1, 42);
    CHECK_EQ(r.rd_value, 42ULL,        "SRLI #0: unchanged");

    r = exec("SRLI #1, R1", 1, 2);
    CHECK_EQ(r.rd_value, 1ULL,         "SRLI #1: 2>>1=1");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,   "SRLI #1: C=0");

    r = exec("SRLI #1, R1", 1, 1);
    CHECK_EQ(r.rd_value, 0ULL,         "SRLI #1: 1>>1=0");
    CHECK_EQ(r.flags & FLAG_C, FLAG_C, "SRLI #1: C=1 (bit 0 was 1)");
    CHECK_EQ(r.flags & FLAG_Z, FLAG_Z, "SRLI #1: Z=1");

    r = exec("SRLI #15, R1", 1, UINT64_C(1) << 15);
    CHECK_EQ(r.rd_value, 1ULL,         "SRLI #15: (1<<15)>>15=1");

    // Logical: no sign extension
    r = exec("SRLI #1, R1", 1, UINT64_C(1) << 63);
    CHECK_EQ(r.rd_value, UINT64_C(1) << 62, "SRLI: logical, no sign extend");
    CHECK_EQ(r.flags & FLAG_S, 0ULL,        "SRLI: S=0");

    r = exec("SRLI #1, R1", 1, UINT64_MAX);
    CHECK_EQ(r.rd_value, UINT64_MAX >> 1, "SRLI UINT64_MAX>>1");
    CHECK_EQ(r.flags & FLAG_C, FLAG_C,    "SRLI UINT64_MAX: C=1");
}

static void test_srai() {
    ExecResult r;

    r = exec("SRAI #0, R1", 1, 42);
    CHECK_EQ(r.rd_value, 42ULL,        "SRAI #0: unchanged");

    r = exec("SRAI #1, R1", 1, 4);
    CHECK_EQ(r.rd_value, 2ULL,         "SRAI #1: 4>>1=2 (positive)");
    CHECK_EQ(r.flags & FLAG_S, 0ULL,   "SRAI #1: S=0");

    r = exec("SRAI #1, R1", 1, 1);
    CHECK_EQ(r.rd_value, 0ULL,         "SRAI #1: 1>>1=0");
    CHECK_EQ(r.flags & FLAG_C, FLAG_C, "SRAI #1: C=1");

    // Arithmetic: sign extends for negative input
    r = exec("SRAI #1, R1", 1, UINT64_C(1) << 63);
    CHECK_EQ(r.rd_value, UINT64_C(3) << 62, "SRAI #1 on MSB: sign extends");
    CHECK_EQ(r.flags & FLAG_S, FLAG_S,      "SRAI #1: S=1");
    CHECK_EQ(r.flags & FLAG_C, 0ULL,        "SRAI #1 on MSB: C=0 (bit 0 was 0)");

    r = exec("SRAI #4, R1", 1, UINT64_C(0x80) << 56);
    CHECK_EQ(r.rd_value, UINT64_C(0xF8) << 56, "SRAI #4: fill top 4 bits with 1");
    CHECK_EQ(r.flags & FLAG_S, FLAG_S,         "SRAI #4: S=1");

    r = exec("SRAI #15, R1", 1, UINT64_C(1) << 15);
    CHECK_EQ(r.rd_value, 1ULL,         "SRAI #15: (1<<15)>>15=1 (positive)");

    r = exec("SRAI #15, R1", 1, UINT64_C(0x8000) << 48);
    CHECK_EQ(r.rd_value, UINT64_C(0xFFFF) << 48, "SRAI #15: 0x8000...>>15=0xFFFF...");
    CHECK_EQ(r.flags & FLAG_S, FLAG_S,            "SRAI #15: S=1");
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
    std::printf("ADD\n");    test_add();
    std::printf("SUB\n");    test_sub();
    std::printf("TEST\n");   test_test();
    std::printf("AND\n");    test_and();
    std::printf("OR\n");     test_or();
    std::printf("XOR\n");    test_xor();
    std::printf("SLL\n");    test_sll();
    std::printf("SRL\n");    test_srl();
    std::printf("SRA\n");    test_sra();
    std::printf("SLLI\n");   test_slli();
    std::printf("SRLI\n");   test_srli();
    std::printf("SRAI\n");   test_srai();
    std::printf("IMM vs REG isolation\n"); test_imm_vs_reg_shift();
    return print_summary();
}
