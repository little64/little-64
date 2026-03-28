#include "test_harness.hpp"

// Special instructions: LSR, SSR, IRET, STOP.
// R0 always-zero invariant (must be tested through cycle(), not dispatchInstruction).

// ---------------------------------------------------------------------------
// STOP — halts the CPU
// ---------------------------------------------------------------------------
static void test_stop() {
    Little64CPU cpu;
    CHECK_TRUE(cpu.isRunning, "CPU starts running");

    cpu.dispatchInstruction(make_instr("STOP"));
    CHECK_FALSE(cpu.isRunning, "STOP: isRunning = false");
}

// ---------------------------------------------------------------------------
// R0 always zero — enforced in cycle(), not dispatchInstruction()
// ---------------------------------------------------------------------------
static void test_r0_always_zero() {
    // LDI to R0: cycle() enforces R0=0 after dispatch
    auto cpu = run_program(
        "LDI #42, R0\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[0], 0ULL, "R0 after LDI: always 0");

    // Arithmetic into R0
    cpu = run_program(
        "LDI #5, R1\n"
        "LDI #3, R2\n"
        "ADD R2, R0\n"    // writing to R0 via ADD
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[0], 0ULL, "R0 after ADD: always 0");

    // Reading from R0 in an operation: should read as 0
    cpu = run_program(
        "LDI #7, R1\n"
        "ADD R0, R1\n"    // R1 = R1 + R0 = 7 + 0 = 7
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[1], 7ULL, "Reading R0 in ADD: reads as 0");
}

// ---------------------------------------------------------------------------
// LSR — load special register (Rs1 = index, Rd = destination)
// Uses SSR first to set known values, then LSR to read them back.
// ---------------------------------------------------------------------------
static void test_lsr() {
    // Round-trip cpu_control (index 0) — set via SSR, read via LSR
    auto cpu = run_program(
        "LDI #0x03, R1\n"    // value to write to cpu_control
        "LDI #0, R2\n"       // index 0 = cpu_control
        "SSR R2, R1\n"       // cpu_control = R1
        "LSR R2, R3\n"       // R3 = cpu_control
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[3], 0x03ULL, "LSR index 0 (cpu_control): round-trip");

    // interrupt_table_base (index 1)
    cpu = run_program(
        "LDI64 #0xDEAD0000, R1\n"
        "LDI #1, R2\n"
        "SSR R2, R1\n"
        "LSR R2, R3\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[3], UINT64_C(0xDEAD0000),
             "LSR index 1 (interrupt_table_base): round-trip");

    // interrupt_mask (index 2)
    cpu = run_program(
        "LDI64 #0xFF, R1\n"
        "LDI #2, R2\n"
        "SSR R2, R1\n"
        "LSR R2, R3\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[3], 0xFFULL, "LSR index 2 (interrupt_mask): round-trip");

    // interrupt_states (index 3) — readable
    cpu = run_program(
        "LDI #0x07, R1\n"
        "LDI #3, R2\n"
        "SSR R2, R1\n"
        "LSR R2, R3\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[3], 0x07ULL, "LSR index 3 (interrupt_states): round-trip");

    // Out-of-range index: should return 0
    cpu = run_program(
        "LDI #63, R2\n"
        "LSR R2, R3\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.regs[3], 0ULL, "LSR out-of-range index: returns 0");
}

// ---------------------------------------------------------------------------
// SSR — store special register (Rs1 = index, Rd = value to write)
// ---------------------------------------------------------------------------
static void test_ssr() {
    // interrupt_table_base (index 1): write then verify via registers struct
    auto cpu = run_program(
        "LDI64 #0xCAFEBABE00000000, R1\n"
        "LDI #1, R2\n"
        "SSR R2, R1\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.interrupt_table_base, UINT64_C(0xCAFEBABE00000000),
             "SSR index 1: interrupt_table_base updated");

    // interrupt_mask (index 2)
    cpu = run_program(
        "LDI64 #0xABCDEF0123456789, R1\n"
        "LDI #2, R2\n"
        "SSR R2, R1\n"
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.interrupt_mask, UINT64_C(0xABCDEF0123456789),
             "SSR index 2: interrupt_mask updated");

    // SSR does NOT update flags
    cpu = run_program(
        "LDI #5, R1\n"
        "LDI #5, R2\n"
        "SUB R2, R1\n"      // Z=1
        "LDI #0x42, R1\n"
        "LDI #1, R2\n"
        "SSR R2, R1\n"      // SSR must not change flags
        "STOP\n"
    );
    CHECK_EQ(cpu.registers.flags & FLAG_Z, FLAG_Z, "SSR does not clear flags");
}

// ---------------------------------------------------------------------------
// IRET — return from interrupt
// Manually configure CPU state to simulate being in an interrupt handler,
// then dispatch IRET and verify all fields are restored correctly.
// ---------------------------------------------------------------------------
static void test_iret() {
    Little64CPU cpu;

    // Set up "we are in an interrupt" state
    const uint64_t saved_pc    = 0x2000;
    const uint64_t saved_flags = FLAG_Z | FLAG_C;
    const uint64_t handler_num = 3;

    cpu.registers.interrupt_epc    = saved_pc;
    cpu.registers.interrupt_eflags = saved_flags;
    cpu.registers.setInInterrupt(true);
    cpu.registers.setInterruptEnabled(false);
    cpu.registers.setCurrentInterruptNumber(handler_num);

    // Execute IRET
    cpu.dispatchInstruction(make_instr("IRET"));

    // PC restored to saved_pc
    CHECK_EQ(cpu.registers.regs[15], saved_pc,    "IRET: PC restored");

    // Flags restored
    CHECK_EQ(cpu.registers.flags, saved_flags,    "IRET: flags restored");

    // Interrupt state cleared
    CHECK_FALSE(cpu.registers.isInInterrupt(),    "IRET: in_interrupt cleared");
    CHECK_TRUE(cpu.registers.isInterruptEnabled(),"IRET: interrupts re-enabled");
    CHECK_EQ(cpu.registers.getCurrentInterruptNumber(), 0ULL,
             "IRET: interrupt number reset to 0");
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------
int main() {
    std::printf("=== Little-64 CPU special instruction tests ===\n\n");
    std::printf("STOP\n");              test_stop();
    std::printf("R0 always zero\n");    test_r0_always_zero();
    std::printf("LSR\n");               test_lsr();
    std::printf("SSR\n");               test_ssr();
    std::printf("IRET\n");              test_iret();
    return print_summary();
}
