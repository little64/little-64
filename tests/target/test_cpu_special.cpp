#include "support/cpu_test_helpers.hpp"
#include "address_translator.hpp"

// Special instructions: LSR, SSR, IRET, STOP.
// R0 always-zero invariant (must be tested through cycle(), not dispatchInstruction).

// ---------------------------------------------------------------------------
// LLR, SCR — load-linked and store-conditional (atomics)
// ---------------------------------------------------------------------------
static void test_llr_scr() {
    // Test LLR/SCR basic execution
    auto cpu = run_program(
        "LDI #0x4000, R1\n"        // address in memory
        "LDI #0x42, R2\n"          // value to load/test
        "LLR R1, R3\n"             // load from address, set reservation
        "SCR R2, R1\n"             // try to store new value
        "STOP\n"
    );

    CHECK_FALSE(cpu.isRunning, "LLR/SCR program completes");
}

static Little64CPU run_llr_scr_invalidation_program(const std::string& interfering_write) {
    return run_program(
        "LDI #0x00, R14\n"
        "LDI.S1 #0x10, R14\n"
        "LDI64 #0x1122334455667788, R1\n"
        "STORE [R14], R1\n"
        "LLR R14, R3\n"
        "LDI #0xAA, R2\n"
        + interfering_write +
        "LDI64 #0x0123456789ABCDEF, R2\n"
        "SCR R14, R2\n"
        "STOP\n");
}

static void test_llr_scr_reservation_invalidates_on_all_write_widths() {
    auto cpu = run_llr_scr_invalidation_program("BYTE_STORE [R14+2], R2\n");
    CHECK_EQ(cpu.registers.flags & FLAG_Z, 0ULL,
             "BYTE_STORE overlapping the reserved 64-bit location invalidates the reservation");
    CHECK_EQ(cpu.getMemoryBus().read8(RAM_BASE + 2), 0xAAULL,
             "BYTE_STORE result remains visible after failed SCR");

    cpu = run_llr_scr_invalidation_program("SHORT_STORE [R14+2], R2\n");
    CHECK_EQ(cpu.registers.flags & FLAG_Z, 0ULL,
             "SHORT_STORE overlapping the reserved 64-bit location invalidates the reservation");
    CHECK_EQ(cpu.getMemoryBus().read16(RAM_BASE + 2), 0x00AAULL,
             "SHORT_STORE result remains visible after failed SCR");

    cpu = run_llr_scr_invalidation_program("WORD_STORE [R14+2], R2\n");
    CHECK_EQ(cpu.registers.flags & FLAG_Z, 0ULL,
             "WORD_STORE overlapping the reserved 64-bit location invalidates the reservation");
    CHECK_EQ(cpu.getMemoryBus().read32(RAM_BASE + 2), 0x000000AAULL,
             "WORD_STORE result remains visible after failed SCR");

    cpu = run_llr_scr_invalidation_program("STORE [R14], R2\n");
    CHECK_EQ(cpu.registers.flags & FLAG_Z, 0ULL,
             "STORE to the reserved 64-bit location invalidates the reservation");
    CHECK_EQ(cpu.getMemoryBus().read64(RAM_BASE), 0xAAULL,
             "STORE result remains visible after failed SCR");
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
static Little64CPU run_special_register_round_trip(const std::string& value_setup,
                                                   uint64_t special_register_id) {
    return run_program(value_setup
                       + ldi_special_register_index(special_register_id, 2)
                       + "SSR R2, R1\n"
                       + "LSR R2, R3\n"
                       + "STOP\n");
}

static Little64CPU run_special_register_write(const std::string& value_setup,
                                              uint64_t special_register_id) {
    return run_program(value_setup
                       + ldi_special_register_index(special_register_id, 2)
                       + "SSR R2, R1\n"
                       + "STOP\n");
}

static void test_lsr() {
    auto cpu = run_special_register_round_trip(
        "LDI #0x03, R1\n",
        Little64SpecialRegisters::kCpuControl);
    CHECK_EQ(cpu.registers.regs[3], 0x03ULL, "LSR cpu_control: round-trip");

    cpu = run_special_register_round_trip(
        "LDI64 #0xDEAD0000, R1\n",
        Little64SpecialRegisters::kInterruptTableBase);
    CHECK_EQ(cpu.registers.regs[3], UINT64_C(0xDEAD0000),
             "LSR interrupt_table_base: round-trip");

    cpu = run_special_register_round_trip(
        "LDI64 #0xFF, R1\n",
        Little64SpecialRegisters::kInterruptMask);
    CHECK_EQ(cpu.registers.regs[3], 0xFFULL, "LSR interrupt_mask: round-trip");

    cpu = run_special_register_round_trip(
        "LDI #0x07, R1\n",
        Little64SpecialRegisters::kInterruptStates);
    CHECK_EQ(cpu.registers.regs[3], 0x07ULL, "LSR interrupt_states: round-trip");

    cpu = run_special_register_round_trip(
        "LDI #0x02, R1\n",
        Little64SpecialRegisters::kInterruptMaskHigh);
    CHECK_EQ(cpu.registers.regs[3], 0x02ULL, "LSR interrupt_mask_high: round-trip");

    cpu = run_special_register_round_trip(
        "LDI #0x04, R1\n",
        Little64SpecialRegisters::kInterruptStatesHigh);
    CHECK_EQ(cpu.registers.regs[3], 0x04ULL, "LSR interrupt_states_high: round-trip");

    cpu = run_special_register_round_trip(
        "LDI64 #0x123456789abcdef0, R1\n",
        Little64SpecialRegisters::kUserThreadPointer);
    CHECK_EQ(cpu.registers.regs[3], UINT64_C(0x123456789abcdef0),
             "LSR user-bank thread_pointer: round-trip");

    constexpr uint64_t kInvalidSpecialRegisterIndex = 63;
    cpu = run_program(
        ldi_special_register_index(kInvalidSpecialRegisterIndex, 2) +
        "LSR R2, R3\n"
        "STOP\n");
    CHECK_EQ(cpu.registers.regs[3], 0ULL, "LSR out-of-range special register: returns 0");
}

// ---------------------------------------------------------------------------
// SSR — store special register (Rs1 = index, Rd = value to write)
// ---------------------------------------------------------------------------
static void test_ssr() {
    auto cpu = run_special_register_write(
        "LDI64 #0xCAFEBABE00000000, R1\n",
        Little64SpecialRegisters::kInterruptTableBase);
    CHECK_EQ(cpu.registers.interrupt_table_base, UINT64_C(0xCAFEBABE00000000),
             "SSR interrupt_table_base: updated");

    cpu = run_special_register_write(
        "LDI64 #0xABCDEF0123456789, R1\n",
        Little64SpecialRegisters::kInterruptMask);
    CHECK_EQ(cpu.registers.interrupt_mask, UINT64_C(0xABCDEF0123456789),
             "SSR interrupt_mask: updated");

    cpu = run_special_register_write(
        "LDI64 #0x0123456789ABCDEF, R1\n",
        Little64SpecialRegisters::kUserThreadPointer);
    CHECK_EQ(cpu.registers.thread_pointer, UINT64_C(0x0123456789ABCDEF),
             "SSR user-bank thread_pointer: updated");

    // SSR does NOT update flags
    cpu = run_program(
        "LDI #5, R1\n"
        "LDI #5, R2\n"
        "SUB R2, R1\n"      // Z=1
        "LDI #0x42, R1\n"
        + ldi_special_register_index(Little64SpecialRegisters::kInterruptTableBase, 2) +
        "SSR R2, R1\n"      // SSR must not change flags
        "STOP\n");
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
    // SYSCALL in supervisor mode: fires TRAP_SYSCALL_FROM_SUPERVISOR
    // (default CPU state is supervisor mode)
    auto cpu = run_program(
        "SYSCALL\n"
        "STOP\n"
    );
    CHECK_FALSE(cpu.isRunning, "SYSCALL in supervisor mode halts CPU (exception not handled)");
    CHECK_EQ(cpu.registers.trap_cause, AddressTranslator::TRAP_SYSCALL_FROM_SUPERVISOR,
             "SYSCALL in supervisor mode: trap_cause matches architectural constant");

    // SYSCALL in user mode: fires TRAP_SYSCALL
    // We need to manually set up user mode since run_program doesn't support it easily
    Little64CPU cpu_user;
    cpu_user.loadProgram(std::vector<uint16_t>{
        0x0000,  // padding
        0x0000   // padding
    });
    cpu_user.registers.setUserMode(true);
    cpu_user.dispatchInstruction(make_instr("SYSCALL"));

    CHECK_FALSE(cpu_user.isRunning, "SYSCALL in user mode halts CPU (exception not handled)");
    CHECK_EQ(cpu_user.registers.trap_cause, AddressTranslator::TRAP_SYSCALL,
             "SYSCALL in user mode: trap_cause matches architectural constant");
}

static void test_invalid_opcode_trap() {
    auto cpu = run_program(
        ".short 0xC500\n"
        "STOP\n"
    );

    CHECK_FALSE(cpu.isRunning, "Invalid opcode trap halts the CPU when no handler exists");
    CHECK_EQ(cpu.registers.trap_cause, AddressTranslator::TRAP_INVALID_INSTRUCTION,
             "Invalid opcode trap uses the architectural invalid-instruction exception code");
    CHECK_EQ(cpu.registers.trap_pc, 0ULL,
             "Invalid opcode trap records the faulting instruction PC");
}

// ---------------------------------------------------------------------------
// User-bank special-register access rules
// ---------------------------------------------------------------------------
static void test_user_mode_thread_pointer_access() {
    Little64CPU cpu;
    cpu.loadProgram(std::vector<uint16_t>{0xDF00});

    cpu.registers.setUserMode(true);
    cpu.registers.regs[1] = Little64SpecialRegisters::kUserThreadPointer;
    cpu.registers.regs[2] = UINT64_C(0xFACEB00C12345678);

    cpu.dispatchInstruction(make_instr("SSR R1, R2"));
    CHECK_EQ(cpu.registers.thread_pointer, UINT64_C(0xFACEB00C12345678),
             "User mode may write the TP special register");
    CHECK_EQ(cpu.registers.trap_cause, 0ULL,
             "User-mode TP write does not raise a privileged instruction trap");

    cpu.registers.regs[3] = 0;
    cpu.dispatchInstruction(make_instr("LSR R1, R3"));
    CHECK_EQ(cpu.registers.regs[3], UINT64_C(0xFACEB00C12345678),
             "User mode may read the TP special register");
    CHECK_EQ(cpu.registers.trap_cause, 0ULL,
             "User-mode TP read does not raise a privileged instruction trap");
}

static void test_user_mode_supervisor_bank_still_traps() {
    Little64CPU cpu;
    cpu.loadProgram(std::vector<uint16_t>{0xDF00});

    cpu.registers.setUserMode(true);
    cpu.registers.regs[1] = Little64SpecialRegisters::kCpuControl;
    cpu.dispatchInstruction(make_instr("LSR R1, R2"));

    CHECK_FALSE(cpu.isRunning, "User-mode supervisor-bank LSR still traps");
    CHECK_EQ(cpu.registers.trap_cause, AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION,
             "Supervisor-bank special registers remain privileged in user mode");
}

static void test_special_register_selector_uses_low_16_bits() {
    Little64CPU cpu;
    cpu.loadProgram(std::vector<uint16_t>{0xDF00});

    cpu.registers.regs[1] = UINT64_C(0xFFFF000000008000);
    cpu.registers.regs[2] = UINT64_C(0x1122334455667788);
    cpu.dispatchInstruction(make_instr("SSR R1, R2"));

    CHECK_EQ(cpu.registers.thread_pointer, UINT64_C(0x1122334455667788),
             "SSR only uses the low 16 selector bits");

    cpu.registers.regs[3] = 0;
    cpu.dispatchInstruction(make_instr("LSR R1, R3"));
    CHECK_EQ(cpu.registers.regs[3], UINT64_C(0x1122334455667788),
             "LSR only uses the low 16 selector bits");
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
    CHECK_EQ(cpu.registers.trap_cause, AddressTranslator::TRAP_EXEC_ALIGN,
             "Trap cause records execute alignment exception");
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
    std::printf("LLR/SCR invalidation\n"); test_llr_scr_reservation_invalidates_on_all_write_widths();
    std::printf("STOP\n");              test_stop();
    std::printf("R0 always zero\n");    test_r0_always_zero();
    std::printf("LSR\n");               test_lsr();
    std::printf("SSR\n");               test_ssr();
    std::printf("IRET\n");              test_iret();
    std::printf("SYSCALL\n");           test_syscall();
    std::printf("Invalid opcode trap\n"); test_invalid_opcode_trap();
    std::printf("User-mode TP access\n"); test_user_mode_thread_pointer_access();
    std::printf("User-bank privilege\n"); test_user_mode_supervisor_bank_still_traps();
    std::printf("Selector masking\n"); test_special_register_selector_uses_low_16_bits();
    std::printf("Execute alignment trap\n"); test_execute_alignment_fault_trap_record();
    return print_summary();
}
