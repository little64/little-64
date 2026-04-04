#include "support/cpu_test_helpers.hpp"

// Special instructions: LSR, SSR, IRET, STOP.
// R0 always-zero invariant (must be tested through cycle(), not dispatchInstruction).

// ---------------------------------------------------------------------------
// LLR, SCR — load-linked and store-conditional (atomics)
// ---------------------------------------------------------------------------
static void test_llr_scr() {
    // Test LLR/SCR basic execution (LLVM backend support is pending)
    // For now, we just verify the instructions don't crash
    Little64CPU cpu;
    cpu.loadProgram(std::vector<uint16_t>{
        0xC191,  // LLR R3, R1 (opcode 3, RS1_RD: rd=3, rs1=1)
        0xC211,  // SCR R2, R1 (opcode 4, RS1_RD: rd=2, rs1=1)
        0xDF00   // STOP
    });

    // Run and verify it doesn't crash
    while (cpu.isRunning) {
        cpu.cycle();
    }

    CHECK_FALSE(cpu.isRunning, "LLR/SCR program completes");
}

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
    // Set up the pre-interrupt cpu_control state that IRET will restore
    // With interrupt enabled (bit 0 = 1), not in interrupt (bit 1 = 0), and interrupt number 0
    cpu.registers.interrupt_cpu_control = 0x1;  // IntEnable=1
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
// SYSCALL — system call instruction (opcode 27)
// ---------------------------------------------------------------------------
static void test_syscall() {
    // SYSCALL in user mode: fires TRAP_SYSCALL (64)
    Little64CPU cpu;
    cpu.loadProgram(std::vector<uint16_t>{0xDB00}); // SYSCALL (opcode 27, NONE)

    cpu.registers.setUserMode(true);
    cpu.cycle();

    CHECK_FALSE(cpu.isRunning, "SYSCALL in user mode halts CPU (exception not handled)");
    CHECK_EQ(cpu.registers.trap_cause, 64ULL, "SYSCALL in user mode: trap_cause = 64");
    CHECK_EQ(cpu.registers.trap_pc, 0ULL, "SYSCALL in user mode: trap_pc = instruction address");

    // SYSCALL in supervisor mode: fires TRAP_SYSCALL_FROM_SUPERVISOR (65)
    cpu = Little64CPU();
    cpu.loadProgram(std::vector<uint16_t>{0xDB00}); // SYSCALL

    cpu.registers.setUserMode(false);
    cpu.cycle();

    CHECK_FALSE(cpu.isRunning, "SYSCALL in supervisor mode halts CPU (exception not handled)");
    CHECK_EQ(cpu.registers.trap_cause, 65ULL, "SYSCALL in supervisor mode: trap_cause = 65");
}

// ---------------------------------------------------------------------------
// Execute translation fault (alignment) populates trap record
// ---------------------------------------------------------------------------
static void test_execute_alignment_fault_trap_record() {
    Little64CPU cpu;
    cpu.loadProgram(std::vector<uint16_t>{0xDF00}); // STOP

    cpu.registers.regs[15] = 1; // force odd PC for execute fetch
    cpu.cycle();

    CHECK_FALSE(cpu.isRunning, "Execute alignment fault halts when exceptions cannot be handled");
    CHECK_EQ(cpu.registers.trap_cause, 62ULL, "Trap cause records execute alignment exception");
    CHECK_EQ(cpu.registers.trap_fault_addr, 1ULL, "Trap fault address stores offending virtual address");
    CHECK_EQ(cpu.registers.trap_access, 2ULL, "Trap access stores execute access kind");
    CHECK_EQ(cpu.registers.trap_pc, 1ULL, "Trap PC stores faulting PC");
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------
int main() {
    std::printf("=== Little-64 CPU special instruction tests ===\n\n");
    std::printf("LLR/SCR\n");           test_llr_scr();
    std::printf("STOP\n");              test_stop();
    std::printf("R0 always zero\n");    test_r0_always_zero();
    std::printf("LSR\n");               test_lsr();
    std::printf("SSR\n");               test_ssr();
    std::printf("IRET\n");              test_iret();
    std::printf("SYSCALL\n");           test_syscall();
    std::printf("Execute alignment trap\n"); test_execute_alignment_fault_trap_record();
    return print_summary();
}
