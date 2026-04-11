#pragma once

#include <cstdint>
#include <array>
#include <vector>
#include <string>
#include <memory>
#include <fstream>
#include "device.hpp"
#include "trace_writer.hpp"
#include "memory_bus.hpp"
#include "serial_device.hpp"
#include "address_translator.hpp"
#include "emulator_clock.hpp"

class Little64CPU : public InterruptSink {
public:
    Little64CPU();
    ~Little64CPU() = default;
    Little64CPU(Little64CPU&&) = default;
    Little64CPU& operator=(Little64CPU&&) = default;

    struct Registers {
        // R0 is defined to always be zero, and writes to it are ignored.
        //  This is implemented by just setting regs[0] to zero at the beginning of every instruction execution.
        // R1-R10 are general-purpose registers.
        // R11 and R12 are reserved for now.
        // R13 is the stack pointer (SP) used for function calls and local variable storage.
        // R14 is the link register (LR) used for function calls.
        // R15 is the program counter (PC) and is updated automatically by the CPU when instructions are executed.
        uint64_t regs[16];

        // Flag bits:
        //   bit 0: Zero (Z)  — result was zero
        //   bit 1: Carry (C) — unsigned overflow/borrow
        //   bit 2: Sign (S)  — result was negative (MSB set)
        // JUMP.GT fires when Z=0 and S=0; JUMP.LT fires when S=1.
        uint64_t flags;

        // Special register space and helper methods
        //   bit 0: Interrupt enable
        //   bit 1: In interrupt
        //   bits 2..8: currently handled interrupt number (if in interrupt)
        //   bit 16: Paging enable
        //   bit 17: User mode
        uint64_t cpu_control;
        
        constexpr bool isInterruptEnabled() const {
            return (cpu_control & 1) != 0;
        }
        constexpr void setInterruptEnabled(bool enabled) {
            if (enabled) {
                cpu_control |= 1;
            } else {
                cpu_control &= ~1;
            }
        }

        constexpr bool isInInterrupt() const {
            return (cpu_control & 2) != 0;
        }
        constexpr void setInInterrupt(bool in_interrupt) {
            if (in_interrupt) {
                cpu_control |= 2;
            } else {
                cpu_control &= ~2;
            }
        }

        constexpr uint8_t getCurrentInterruptNumber() const {
            return (cpu_control >> 2) & 0x3F;
        }
        constexpr void setCurrentInterruptNumber(uint8_t num) {
            cpu_control = (cpu_control & ~0xFC) | ((num & 0x3F) << 2);
        }

        static constexpr uint64_t CPU_CONTROL_PAGING_ENABLE = 1ULL << 16;

        constexpr bool isPagingEnabled() const {
            return (cpu_control & CPU_CONTROL_PAGING_ENABLE) != 0;
        }
        constexpr void setPagingEnabled(bool enabled) {
            if (enabled) {
                cpu_control |= CPU_CONTROL_PAGING_ENABLE;
            } else {
                cpu_control &= ~CPU_CONTROL_PAGING_ENABLE;
            }
        }

        static constexpr uint64_t CPU_CONTROL_USER_MODE = 1ULL << 17;

        constexpr bool isUserMode() const {
            return (cpu_control & CPU_CONTROL_USER_MODE) != 0;
        }
        constexpr void setUserMode(bool user) {
            if (user) {
                cpu_control |= CPU_CONTROL_USER_MODE;
            } else {
                cpu_control &= ~CPU_CONTROL_USER_MODE;
            }
        }


        // Stores pointer to interrupt handler table (base address of an array of 64-bit handler addresses)
        uint64_t interrupt_table_base;
        // Each bit corresponds to an interrupt number; if set, the corresponding interrupt is unmasked and can be triggered.
        uint64_t interrupt_mask;
        // Each bit corresponds to an interrupt number; if set, the corresponding interrupt is currently active/pending.
        // The CPU will set/clear bits automatically; setting bits from software causes an interrupt.
        uint64_t interrupt_states;

        // Trap information register block.
        // These are populated by the CPU when an exception is raised.
        // They are intentionally typed fields to make paging/MMU integration predictable.
        //   trap_cause      - architecture-defined exception code
        //   trap_fault_addr - relevant faulting virtual address (if any)
        //   trap_access     - 0=read, 1=write, 2=execute
        //   trap_pc         - PC associated with the faulting operation
        //   trap_aux        - reserved for future architecture-defined metadata

        uint64_t interrupt_epc;
        uint64_t interrupt_eflags;
        uint64_t interrupt_cpu_control;
        uint64_t trap_cause;
        uint64_t trap_fault_addr;
        uint64_t trap_access;
        uint64_t trap_pc;
        uint64_t trap_aux;
        uint64_t page_table_root_physical;
        uint64_t boot_info_frame_physical;
        uint64_t boot_source_page_size;
        uint64_t boot_source_page_count;
        uint64_t hypercall_caps;

        // Load-Linked / Store-Conditional reservation state
        // (not special registers, but internal CPU state for atomics)
        uint64_t ll_reservation_addr = 0;    // address of the reserved location
        bool ll_reservation_valid = false;   // is the reservation still valid?

        uint64_t getSpecialRegister(uint64_t index) const {
            switch (index) {
                case 0: return cpu_control;
                case 1: return interrupt_table_base;
                case 2: return interrupt_mask;
                case 3: return interrupt_states;
                case 4: return interrupt_epc;
                case 5: return interrupt_eflags;
                case 6: return trap_cause;
                case 7: return trap_fault_addr;
                case 8: return trap_access;
                case 9: return trap_pc;
                case 10: return trap_aux;
                case 11: return page_table_root_physical;
                case 12: return boot_info_frame_physical;
                case 13: return boot_source_page_size;
                case 14: return boot_source_page_count;
                case 15: return hypercall_caps;
                case 16: return interrupt_cpu_control;
                default: return 0;
            }
        }

        void setSpecialRegister(uint64_t index, uint64_t value) {
            switch (index) {
                case 0: cpu_control = value; break;
                case 1: interrupt_table_base = value; break;
                case 2: interrupt_mask = value; break;
                case 3: interrupt_states = value; break;
                case 4: interrupt_epc = value; break;
                case 5: interrupt_eflags = value; break;
                case 6: trap_cause = value; break;
                case 7: trap_fault_addr = value; break;
                case 8: trap_access = value; break;
                case 9: trap_pc = value; break;
                case 10: trap_aux = value; break;
                case 11: page_table_root_physical = value; break;
                case 12: boot_info_frame_physical = value; break;
                case 13: boot_source_page_size = value; break;
                case 14: boot_source_page_count = value; break;
                case 15: hypercall_caps = value; break;
                case 16: interrupt_cpu_control = value; break;
            }
        }

        Registers() {
            for (int i = 0; i < 16; ++i)
                regs[i] = 0;
            flags = 0;
            
            cpu_control = 0;
            
            interrupt_table_base = 0;
            interrupt_mask = 0;
            interrupt_states = 0;
            interrupt_epc = 0;
            interrupt_eflags = 0;
            interrupt_cpu_control = 0;
            trap_cause = 0;
            trap_fault_addr = 0;
            trap_access = 0;
            trap_pc = 0;
            trap_aux = 0;
            page_table_root_physical = 0;
            boot_info_frame_physical = 0;
            boot_source_page_size = 0;
            boot_source_page_count = 0;
            hypercall_caps = 0;
        }
    };

    struct Instruction {
        bool operator==(const Instruction& other) const {
            return _raw == other._raw;
        }

        // bits[15:14]: 0=LS_REG, 1=LS_PCREL, 2=LDI, 3=extended
        uint8_t format = 0;

        // Common to all formats
        uint8_t rd = 0;         // bits[3:0]

        // Formats 00 and 01: LS opcode (4 bits, bits[13:10])
        uint8_t opcode_ls = 0;

        // Format 00 (LS Register)
        uint8_t offset2 = 0;    // bits[9:8]: unsigned, byte offset = offset2 * 2
        uint8_t rs1 = 0;        // bits[7:4]  (also used by format 11)

        // Format 01 (LS PC-Relative)
        // For non-JUMP opcodes: bits[9:4] are the 6-bit signed offset; bits[3:0] are Rd.
        // For JUMP.* opcodes (11–15): bits[9:0] are the 10-bit signed offset; Rd is always R15.
        int16_t pc_rel = 0;     // signed offset in instruction units; byte offset = pc_rel * 2

        // Format 10 (Load Immediate)
        uint8_t shift = 0;      // bits[13:12]
        uint8_t imm8 = 0;       // bits[11:4]

        // Format 11 extensions:
        //   110 = GP ALU, opcode bits [12:8] (5 bits)
        //   111 = unconditional PC-relative jump, offset bits [12:0] (13-bit signed)
        bool is_unconditional_jump = false;
        uint8_t opcode_gp = 0;  // bits[12:8] (5 bits) for 110 GP
        // rs1 reused at bits[7:4] for GP

        Instruction() = default;
        Instruction(uint16_t raw) : _raw(raw) {
            format = (raw >> 14) & 0x3;
            rd     = raw & 0xF;

            switch (format) {
                case 0: // LS Register
                    opcode_ls = (raw >> 10) & 0xF;
                    offset2   = (raw >> 8)  & 0x3;
                    rs1       = (raw >> 4)  & 0xF;
                    break;
                case 1: { // LS PC-Relative
                    opcode_ls = (raw >> 10) & 0xF;
                    if (opcode_ls >= 11 && opcode_ls <= 15) {
                        // JUMP.* opcodes: 10-bit signed offset in bits[9:0], Rd implicit = R15
                        uint16_t raw10 = raw & 0x3FF;
                        pc_rel = (raw10 & 0x200) ? (int16_t)(raw10 | 0xFC00) : (int16_t)raw10;
                        rd = 15;
                    } else {
                        uint8_t raw6 = (raw >> 4) & 0x3F;
                        pc_rel = (raw6 & 0x20) ? (int16_t)(int8_t)(raw6 | 0xC0) : (int16_t)raw6;
                    }
                    break;
                }
                case 2: // Load Immediate
                    shift = (raw >> 12) & 0x3;
                    imm8  = (raw >> 4)  & 0xFF;
                    break;
                case 3: // Extended: GP ALU (110) or unconditional JUMP (111)
                    is_unconditional_jump = ((raw >> 13) & 0x1) != 0;
                    if (is_unconditional_jump) {
                        uint16_t raw13 = raw & 0x1FFF;
                        pc_rel = (raw13 & 0x1000) ? (int16_t)(raw13 | 0xE000) : (int16_t)raw13;
                        rd = 15;
                    } else {
                        opcode_gp = (raw >> 8) & 0x1F;
                        rs1       = (raw >> 4) & 0xF;
                    }
                    break;
            }
        }

        uint16_t encode() const {
            uint16_t raw = 0;
            raw |= (format & 0x3) << 14;

            switch (format) {
                case 0:
                    raw |= (opcode_ls & 0xF) << 10;
                    raw |= (offset2   & 0x3) << 8;
                    raw |= (rs1       & 0xF) << 4;
                    raw |= (rd        & 0xF);
                    break;
                case 1:
                    raw |= (opcode_ls & 0xF) << 10;
                    if (opcode_ls >= 11 && opcode_ls <= 15) {
                        // JUMP.* opcodes: 10-bit signed offset in bits[9:0], Rd implicit = R15
                        raw |= (uint16_t)pc_rel & 0x3FF;
                    } else {
                        raw |= ((uint16_t)pc_rel & 0x3F) << 4;
                        raw |= (rd & 0xF);
                    }
                    break;
                case 2:
                    raw |= (shift & 0x3)  << 12;
                    raw |= (imm8  & 0xFF) << 4;
                    raw |= (rd    & 0xF);
                    break;
                case 3:
                    if (is_unconditional_jump) {
                        raw |= 1 << 13; // 111 prefix
                        raw |= (uint16_t)pc_rel & 0x1FFF;
                    } else {
                        raw |= (opcode_gp & 0x1F) << 8;
                        raw |= (rs1       & 0xF)  << 4;
                        raw |= (rd        & 0xF);
                    }
                    break;
            }
            return raw;
        }

    private:
        uint16_t _raw = 0;
    };

    void cycle();
    void dispatchInstruction(const Instruction& instr);

    // Load program words as a ROM region (4K-aligned) at base address.
    // Creates ROM + 64MB RAM + serial device. Resets CPU state.
    // `entry_offset` specifies the start PC relative to base (defaults to 0).
    void loadProgram(const std::vector<uint16_t>& words, uint64_t base = 0, uint64_t entry_offset = 0);

    // Load a linked ELF image into RAM at base address. Entry point is taken from e_entry.
    // Returns true if loading succeeded, false on error.
    bool loadProgramElf(const std::vector<uint8_t>& elf_bytes, uint64_t base = 0);
    bool loadProgramElfDirectPaged(const std::vector<uint8_t>& elf_bytes,
                                   uint64_t kernel_physical_base = 0x100000,
                                   uint64_t direct_map_virtual_base = 0xFFFFFFC000000000ULL);

    void setBootSourcePages(std::vector<uint8_t> bytes, uint64_t page_size);

    bool _allocatePageTablePage(uint64_t& out_page);

    // Resets CPU and all configured devices.
    void reset();

    // Memory bus access for GUI panels and external tooling
    MemoryBus&       getMemoryBus()       { return _bus; }
    const MemoryBus& getMemoryBus() const { return _bus; }

    // Returns a pointer to the serial device if one is present, or nullptr.
    SerialDevice* getSerial();

    // Enable/disable MMIO trace logging on all attached devices.
    void setMmioTrace(bool enabled);

    // Enable/disable control-flow trace events in the boot event ring.
    // When enabled, non-fallthrough PC changes (branches/returns/interrupt entries)
    // and suspicious targets are recorded to aid lockup debugging.
    void setControlFlowTrace(bool enabled);

    // Dump the boot event log to stderr. No-op if already dumped.
    void dumpBootLog(const char* reason);

    // Enable live boot-event streaming to file. When enabled, every event is
    // written as it occurs, preserving full history beyond the ring buffer.
    // Convenience wrapper: creates a TraceWriter with default config.
    bool setBootEventOutputFile(const std::string& path);

    // Set a pre-configured TraceWriter for boot-event streaming.
    // Ownership transfers to the CPU.
    bool setTraceWriter(std::unique_ptr<TraceWriter> writer);

    // Dump the boot event log to a file path. Returns false on file I/O errors.
    bool dumpBootLogToFile(const char* reason, const std::string& path) const;

    // Assert a hardware interrupt line (sets the bit in interrupt_states).
    // The interrupt will be serviced on the next cycle if enabled and unmasked.
    void assertInterrupt(uint64_t num) override;
    void clearInterrupt(uint64_t num) override;

    // Public register state for GUI panels
    Registers registers;

    bool isRunning = true;

    // Access to virtual clock (for devices and GUI integration)
    EmulatorClock& clock() { return _clock; }
    const EmulatorClock& clock() const { return _clock; }

private:
    struct BootEvent {
        const char* tag = "";
        uint64_t cycle = 0;
        uint64_t pc = 0;
        uint64_t a = 0;
        uint64_t b = 0;
        uint64_t c = 0;
    };

    void _recordBootEvent(const char* tag, uint64_t a = 0, uint64_t b = 0, uint64_t c = 0);
    bool _isLrTracePcInRange(uint64_t pc) const;
    bool _shouldTraceLrLsOp(const Instruction& instr, uint64_t op_pc) const;
    void _recordLrTraceRegs(const char* tag, uint64_t op_pc);
    bool _isPcProbeMatch(uint64_t pc) const;
    void _recordPcProbe(uint64_t pc, uint16_t instr_word);
    bool _isWatchAddrInRange(uint64_t addr) const;
    void _writeBootEvents(std::ostream& out, const char* reason) const;
    void _dumpBootEvents(const char* reason);

    EmulatorClock _clock;
    void _dispatchLSReg(const Instruction& instr);
    void _dispatchLSPCRel(const Instruction& instr);
    void _dispatchLDI(const Instruction& instr);
    void _dispatchGP(const Instruction& instr);
    void _dispatchUJMP(const Instruction& instr);

    void _updateFlags(uint64_t result, bool carry = false);

    bool _raiseInterrupt(uint64_t interrupt_number, bool exception = false,
                         uint64_t epc = UINT64_MAX);

    enum class CpuAccessType : uint8_t {
        Read = 0,
        Write = 1,
        Execute = 2,
    };

    struct TranslationResult {
        bool valid = true;
        uint64_t physical = 0;
        uint64_t trap_cause = 0;
        uint64_t trap_aux = 0;
    };

    TranslationResult _translateAddress(uint64_t virtual_addr, CpuAccessType access) const;

    // Inline fast-path: identity-maps when paging is off, checks TLB when paging
    // is on.  Falls through to _mapAddressSlowPath for TLB misses and faults.
    inline bool _mapAddress(uint64_t virtual_addr, CpuAccessType access,
                            uint64_t operation_pc, uint64_t& physical_out) {
        // Execute alignment check must happen before any shortcut.
        if (__builtin_expect(access == CpuAccessType::Execute && (virtual_addr & 0x1ULL), 0)) {
            return _mapAddressSlowPath(virtual_addr, access, operation_pc, physical_out);
        }
        if (__builtin_expect(!registers.isPagingEnabled(), 1)) {
            physical_out = virtual_addr;
            return true;
        }
        // TLB lookup
        const uint64_t vpage = virtual_addr >> 12;
        const size_t idx = vpage & kTLBMask;
        const TLBEntry& entry = _tlb[idx];
        if (__builtin_expect(entry.vpage == vpage, 1)) {
            const uint8_t access_bit = 1u << static_cast<uint8_t>(access);
            if (__builtin_expect((entry.perms & access_bit) != 0, 1)) {
                if (!registers.isUserMode() || entry.user_accessible) {
                    physical_out = entry.pbase | (virtual_addr & 0xFFFULL);
                    return true;
                }
            }
        }
        return _mapAddressSlowPath(virtual_addr, access, operation_pc, physical_out);
    }

    bool _mapAddressSlowPath(uint64_t virtual_addr, CpuAccessType access,
                             uint64_t operation_pc, uint64_t& physical_out);

    void _executeHypercall();

    uint8_t  _readMemory8 (uint64_t addr, uint64_t operation_pc, CpuAccessType access = CpuAccessType::Read);
    void     _writeMemory8(uint64_t addr, uint8_t v, uint64_t operation_pc);
    uint16_t _readMemory16(uint64_t addr, uint64_t operation_pc, CpuAccessType access = CpuAccessType::Read);
    void     _writeMemory16(uint64_t addr, uint16_t v, uint64_t operation_pc);
    uint32_t _readMemory32(uint64_t addr, uint64_t operation_pc, CpuAccessType access = CpuAccessType::Read);
    void     _writeMemory32(uint64_t addr, uint32_t v, uint64_t operation_pc);
    uint64_t _readMemory64(uint64_t addr, uint64_t operation_pc, CpuAccessType access = CpuAccessType::Read);
    void     _writeMemory64(uint64_t addr, uint64_t v, uint64_t operation_pc);

    MemoryBus _bus;
    std::vector<Device*> _devices;
    AddressTranslator _translator;
    uint64_t _page_table_alloc_cursor = 0;
    uint64_t _mem_base = 0;
    uint64_t _mem_size = 0;
    std::vector<uint8_t> _boot_source_bytes;

    // Software TLB — direct-mapped, 64-entry, covers 4K pages.
    struct TLBEntry {
        uint64_t vpage = UINT64_MAX;   // virtual page number (addr >> 12)
        uint64_t pbase = 0;            // physical page base (aligned)
        uint8_t  perms = 0;            // bit 0=R, 1=W, 2=X
        bool     user_accessible = false;
    };
    static constexpr size_t kTLBSize = 64;
    static constexpr size_t kTLBMask = kTLBSize - 1;
    std::array<TLBEntry, kTLBSize> _tlb{};
    void _flushTLB();

    static constexpr size_t kBootEventCapacity = 128;
    std::array<BootEvent, kBootEventCapacity> _boot_events{};
    size_t _boot_event_head = 0;
    bool _boot_event_wrapped = false;
    bool _boot_event_dumped = false;
    uint64_t _cycle_count = 0;
    bool _trace_control_flow = false;
    bool _trace_lr = false;
    uint64_t _trace_lr_window_start = 0;
    uint64_t _trace_lr_window_end = UINT64_MAX;
    bool _trace_watch = false;
    uint64_t _trace_watch_start = 0;
    uint64_t _trace_watch_end = 0;
    bool _trace_pc_probe = false;
    bool _trace_pc_probe_deref = false;
    uint64_t _trace_pc_probe0 = 0;
    uint64_t _trace_pc_probe1 = 0;
    uint64_t _trace_pc_probe_limit = UINT64_MAX;
    std::unique_ptr<TraceWriter> _trace_writer;

    // Combined flag: true when any debug trace is active. Allows the hot loop
    // to skip all trace checks with a single branch when tracing is off.
    bool _any_trace_active = false;
    void _updateAnyTraceActive();
};
