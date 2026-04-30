#include "cpu.hpp"
#include "lite_sdcard_device.hpp"
#include "lite_uart_device.hpp"
#include "machine_config.hpp"
#include "opcodes.hpp"
#include "page_table_builder.hpp"
#include "dtb_loader.hpp"
#include "ram_region.hpp"
#include <memory>
#include <algorithm>
#include <cerrno>
#include <cstring>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <elf.h>

#ifndef EM_LITTLE64
#define EM_LITTLE64 0x4C36
#endif

Little64CPU::Little64CPU() {
    auto parse_env_u64 = [](const char* name, uint64_t& out) -> bool {
        const char* env_val = std::getenv(name);
        if (!env_val || env_val[0] == '\0') {
            return false;
        }

        char* end = nullptr;
        errno = 0;
        const unsigned long long parsed = std::strtoull(env_val, &end, 0);
        if (errno != 0 || end == env_val || !end || *end != '\0') {
            return false;
        }

        out = static_cast<uint64_t>(parsed);
        return true;
    };

    const char* env = std::getenv("LITTLE64_TRACE_CONTROL_FLOW");
    _trace_control_flow = (env && env[0] == '1');

    const char* env_trace_lr = std::getenv("LITTLE64_TRACE_LR");
    _trace_lr = (env_trace_lr && env_trace_lr[0] == '1');

    if (_trace_lr) {
        parse_env_u64("LITTLE64_TRACE_LR_START", _trace_lr_window_start);
        parse_env_u64("LITTLE64_TRACE_LR_END", _trace_lr_window_end);

        if (_trace_lr_window_end < _trace_lr_window_start) {
            const uint64_t tmp = _trace_lr_window_start;
            _trace_lr_window_start = _trace_lr_window_end;
            _trace_lr_window_end = tmp;
        }
    }

    const char* env_trace_watch = std::getenv("LITTLE64_TRACE_WATCH");
    _trace_watch = (env_trace_watch && env_trace_watch[0] == '1');
    if (_trace_watch) {
        bool has_start = parse_env_u64("LITTLE64_TRACE_WATCH_START", _trace_watch_start);
        bool has_end = parse_env_u64("LITTLE64_TRACE_WATCH_END", _trace_watch_end);
        if (!has_start && !has_end) {
            _trace_watch = false;
        } else if (!has_start) {
            _trace_watch_start = _trace_watch_end;
        } else if (!has_end) {
            _trace_watch_end = _trace_watch_start;
        }

        if (_trace_watch && _trace_watch_end < _trace_watch_start) {
            const uint64_t tmp = _trace_watch_start;
            _trace_watch_start = _trace_watch_end;
            _trace_watch_end = tmp;
        }
    }

    const char* env_trace_pc_probe = std::getenv("LITTLE64_TRACE_PC_PROBE");
    _trace_pc_probe = (env_trace_pc_probe && env_trace_pc_probe[0] == '1');
    const char* env_trace_pc_probe_deref = std::getenv("LITTLE64_TRACE_PC_PROBE_DEREF");
    _trace_pc_probe_deref = (env_trace_pc_probe_deref && env_trace_pc_probe_deref[0] == '1');
    if (_trace_pc_probe) {
        bool has_pc0 = parse_env_u64("LITTLE64_TRACE_PC_PROBE0", _trace_pc_probe0);
        bool has_pc1 = parse_env_u64("LITTLE64_TRACE_PC_PROBE1", _trace_pc_probe1);
        if (!has_pc0 && !has_pc1) {
            _trace_pc_probe = false;
        } else if (!has_pc0) {
            _trace_pc_probe0 = _trace_pc_probe1;
        } else if (!has_pc1) {
            _trace_pc_probe1 = _trace_pc_probe0;
        }

        parse_env_u64("LITTLE64_TRACE_PC_PROBE_LIMIT", _trace_pc_probe_limit);
    }

    _updateAnyTraceActive();
}

namespace {

struct CpuPageAllocator : public PageTableBuilder::Allocator {
    explicit CpuPageAllocator(Little64CPU& cpu_ref) : cpu(cpu_ref) {}

    bool allocatePage(uint64_t& out_physical_page) override {
        return cpu._allocatePageTablePage(out_physical_page);
    }

    Little64CPU& cpu;
};

constexpr uint64_t HYPERCALL_MEMINFO = 1;
constexpr uint64_t HYPERCALL_GET_BOOT_SOURCE_INFO = 2;
constexpr uint64_t HYPERCALL_READ_BOOT_SOURCE_PAGES = 3;

constexpr uint64_t HYPERCALL_STATUS_OK = 0;
constexpr uint64_t HYPERCALL_STATUS_INVALID = 1;
constexpr uint64_t HYPERCALL_STATUS_UNSUPPORTED = 2;
constexpr uint64_t HYPERCALL_STATUS_RANGE = 3;

constexpr uint64_t HYPERCALL_CAP_MINIMAL_BOOT = 1;
// Keep MMIO out of RAM but in low physical space for early Linux/device access.
constexpr uint64_t SERIAL_BASE = 0x08000000ULL;
constexpr uint64_t TIMER_BASE = 0x08001000ULL;
constexpr uint64_t PVBLK_BASE = 0x08002000ULL;
constexpr uint64_t LITEX_BOOTROM_BASE = 0x00000000ULL;
constexpr uint64_t LITEX_BOOTROM_SIZE = 0x00008000ULL;
constexpr uint64_t LITEX_BOOTROM_RAM_BASE = 0x40000000ULL;
constexpr uint64_t LITEX_FLASH_BASE = 0x20000000ULL;
constexpr uint64_t LITEX_FLASH_WINDOW_SIZE = 0x01000000ULL;
constexpr uint64_t LITEX_SRAM_BASE = 0x10000000ULL;
constexpr uint64_t LITEX_SRAM_SIZE = 0x00004000ULL;
// Keep the canonical bootrom-first Little64 LiteX helper contract in sync with
// hdl/little64_cores/litex_soc.py and the generated DTS/stage-0 artifacts.
// The explicit manual litex-flash + --disk compatibility path below is the one
// intentional exception: it still uses the legacy LiteUART slot at 0xF0003800.
constexpr uint64_t LITEX_SDCARD_BASE = 0xF0000800ULL;
constexpr uint64_t LITEX_UART_BASE = 0xF0001000ULL;
constexpr uint64_t LITEX_SDRAM_CSR_BASE = 0xF0003000ULL;
constexpr uint64_t LITEX_SDRAM_CSR_SIZE = 0x00000100ULL;
constexpr uint64_t LITEX_FLASH_SD_UART_BASE = 0xF0003800ULL;
constexpr uint64_t LITEX_BOOTROM_SD_UART_BASE = 0xF0004000ULL;
constexpr uint64_t LITEX_FLASH_RAM_SIZE = 64 * 1024 * 1024ULL;
constexpr uint64_t LITEX_BOOTROM_RAM_SIZE = 256 * 1024 * 1024ULL;

} // namespace

bool Little64CPU::_isLrTracePcInRange(uint64_t pc) const {
    return pc >= _trace_lr_window_start && pc <= _trace_lr_window_end;
}

bool Little64CPU::_isWatchAddrInRange(uint64_t addr) const {
    return _trace_watch && addr >= _trace_watch_start && addr <= _trace_watch_end;
}

bool Little64CPU::_shouldTraceLrLsOp(const Instruction& instr, uint64_t op_pc) const {
    if (!_trace_lr || !_isLrTracePcInRange(op_pc)) {
        return false;
    }

    const LS::Opcode op = static_cast<LS::Opcode>(instr.opcode_ls);
    if (op != LS::Opcode::PUSH && op != LS::Opcode::POP && op != LS::Opcode::MOVE) {
        return false;
    }

    return instr.rd == 14 || instr.rd == 15 || instr.rs1 == 14 || instr.rs1 == 15;
}

void Little64CPU::_recordLrTraceRegs(const char* tag, uint64_t op_pc) {
    _recordBootEvent(tag, op_pc, registers.regs[13], registers.regs[14]);
    _recordBootEvent("lr-r15", op_pc, registers.regs[15], registers.flags);
    _recordBootEvent("lr-r1r12", op_pc, registers.regs[1], registers.regs[12]);
}

bool Little64CPU::_isPcProbeMatch(uint64_t pc) const {
    if (!_trace_pc_probe) {
        return false;
    }

    return pc == _trace_pc_probe0 || pc == _trace_pc_probe1;
}

void Little64CPU::_recordPcProbe(uint64_t pc, uint16_t instr_word) {
    if (!_isPcProbeMatch(pc)) {
        return;
    }

    if (_trace_pc_probe_limit == 0) {
        return;
    }

    _recordBootEvent("pc-probe", pc, instr_word, registers.flags);
    _recordBootEvent("pc-probe-r8r9", pc, registers.regs[8], registers.regs[9]);
    _recordBootEvent("pc-probe-r10r1", pc, registers.regs[10], registers.regs[1]);
    _recordBootEvent("pc-probe-r3r4", pc, registers.regs[3], registers.regs[4]);
    _recordBootEvent("pc-probe-r5r12", pc, registers.regs[5], registers.regs[12]);
    _recordBootEvent("pc-probe-r6r7", pc, registers.regs[6], registers.regs[7]);
    _recordBootEvent("pc-probe-r2r11", pc, registers.regs[2], registers.regs[11]);
    _recordBootEvent("pc-probe-r14r15", pc, registers.regs[14], registers.regs[15]);
    if (_trace_pc_probe_deref) {
        const uint64_t r10 = registers.regs[10];
        const uint64_t r11 = registers.regs[11];
        if (r10 != 0) {
            const uint64_t r10w0 = _readMemory64(r10, pc, CpuAccessType::Read);
            const uint64_t r10w1 = _readMemory64(r10 + 8, pc, CpuAccessType::Read);
            const uint64_t r10w2 = _readMemory64(r10 + 16, pc, CpuAccessType::Read);
            const uint64_t r10w3 = _readMemory64(r10 + 24, pc, CpuAccessType::Read);
            const uint64_t r10w4 = _readMemory64(r10 + 32, pc, CpuAccessType::Read);
            const uint64_t r10w5 = _readMemory64(r10 + 40, pc, CpuAccessType::Read);
            _recordBootEvent("pc-probe-r10mem0", pc, r10w0, r10w1);
            _recordBootEvent("pc-probe-r10mem1", pc, r10w2, r10);
            _recordBootEvent("pc-probe-r10mem2", pc, r10w3, r10 + 24);
            _recordBootEvent("pc-probe-r10mem3", pc, r10w4, r10 + 32);
            _recordBootEvent("pc-probe-r10mem4", pc, r10w5, r10 + 40);
        }
        if (r11 != 0) {
            const uint64_t r11w0 = _readMemory64(r11, pc, CpuAccessType::Read);
            const uint64_t r11w1 = _readMemory64(r11 + 8, pc, CpuAccessType::Read);
            _recordBootEvent("pc-probe-r11mem", pc, r11w0, r11w1);
        }
    }

    --_trace_pc_probe_limit;
}

void Little64CPU::_recordBootEvent(const char* tag, uint64_t a, uint64_t b, uint64_t c) {
    BootEvent& ev = _boot_events[_boot_event_head];
    ev.tag = tag;
    ev.cycle = _cycle_count;
    ev.pc = registers.regs[15];
    ev.a = a;
    ev.b = b;
    ev.c = c;

    _boot_event_head = (_boot_event_head + 1) % kBootEventCapacity;
    if (_boot_event_head == 0) {
        _boot_event_wrapped = true;
    }

    if (_trace_writer) {
        _trace_writer->writeEvent(ev.tag, ev.cycle, ev.pc, ev.a, ev.b, ev.c);
    }
}

void Little64CPU::_dumpBootEvents(const char* reason) {
    if (_boot_event_dumped) {
        return;
    }
    _boot_event_dumped = true;

    _writeBootEvents(std::cerr, reason);
}

void Little64CPU::_writeBootEvents(std::ostream& out, const char* reason) const {
    out << "[little64] boot-debug: " << reason << "\n";
    out << "[little64] boot-debug: last events (oldest to newest)\n";

    const size_t count = _boot_event_wrapped ? kBootEventCapacity : _boot_event_head;
    const size_t start = _boot_event_wrapped ? _boot_event_head : 0;
    for (size_t i = 0; i < count; ++i) {
        const size_t idx = (start + i) % kBootEventCapacity;
        const BootEvent& ev = _boot_events[idx];
        out << "  [" << ev.cycle << "] " << ev.tag
            << " pc=0x" << std::hex << ev.pc
            << " a=0x" << ev.a
            << " b=0x" << ev.b
            << " c=0x" << ev.c
            << std::dec << "\n";
    }
}

void Little64CPU::_flushTLB() {
    for (auto& e : _tlb) {
        e.vpage = UINT64_MAX;
    }
}

void Little64CPU::_updateAnyTraceActive() {
    _any_trace_active = _trace_control_flow || _trace_lr || _trace_watch || _trace_pc_probe;
}

void Little64CPU::reset() {
    registers = {};
    isRunning = true;
    _boot_event_head = 0;
    _boot_event_wrapped = false;
    _boot_event_dumped = false;
    _cycle_count = 0;
    _clock.resume();  // Start the virtual clock so timer devices can fire
    _flushTLB();
    _recordBootEvent("reset");
    for (Device* device : _devices) {
        if (device) {
            device->reset();
        }
    }
}

void Little64CPU::setDiskImage(std::unique_ptr<DiskImage> image) {
    _disk_image = std::move(image);
}

void Little64CPU::cycle() {
    if (!isRunning)
        return;
    ++_cycle_count;

    // R0 is always zero
    registers.regs[0] = 0;

    uint64_t pc = registers.regs[15];
    uint16_t instr_word = _readMemory16(pc, pc, CpuAccessType::Execute);
    if (!isRunning) {
        _recordBootEvent("fetch-failed", pc, instr_word, registers.trap_cause);
        _dumpBootEvents("execution stopped during fetch");
        return;
    }
    Instruction instr(instr_word);

    // Trace checks gated behind combined flag — zero overhead when tracing is off.
    if (__builtin_expect(_any_trace_active, 0)) {
        _recordPcProbe(pc, instr_word);
    }
    const uint64_t r1_before  = __builtin_expect(_any_trace_active, 0) ? registers.regs[1]  : 0;
    const uint64_t r11_before = __builtin_expect(_any_trace_active, 0) ? registers.regs[11] : 0;

    registers.regs[15] += 2;  // advance PC before dispatch (so pc_rel is relative to next instruction)

    dispatchInstruction(instr);

    if (__builtin_expect(_any_trace_active, 0)) {
        if (_trace_lr && _isLrTracePcInRange(pc) && registers.regs[1] != r1_before) {
            _recordBootEvent("r1-change", pc, r1_before, registers.regs[1]);
            _recordBootEvent("r1-change-op", pc, instr_word, registers.regs[12]);
        }
        if (_trace_lr && _isLrTracePcInRange(pc) && registers.regs[11] != r11_before) {
            _recordBootEvent("r11-change", pc, r11_before, registers.regs[11]);
            _recordBootEvent("r11-change-op", pc, instr_word, registers.regs[13]);
        }

        const uint64_t next_pc = registers.regs[15];
        const uint64_t fallthrough_pc = pc + 2;
        if (_trace_control_flow && next_pc != fallthrough_pc) {
            _recordBootEvent("pc-flow", pc, next_pc, instr_word);
        }
        if (_trace_control_flow && (next_pc & 1ULL)) {
            _recordBootEvent("pc-odd", pc, next_pc, instr_word);
        }
        if (_trace_control_flow && next_pc < _mem_base) {
            _recordBootEvent("pc-below-ram", pc, next_pc, _mem_base);
        }
    }

    // If interrupts are disabled and control flow returns to the same PC,
    // execution cannot make forward progress and cannot be externally broken
    // by interrupt delivery. Stop immediately before the event ring is flooded.
    {
        const uint64_t next_pc = registers.regs[15];
        if (isRunning && next_pc == pc && !registers.isInterruptEnabled()) {
            _recordBootEvent("self-loop-lockup", pc, instr_word, registers.cpu_control);
            isRunning = false;
            _dumpBootEvents("self-loop while interrupts disabled");
            return;
        }
    }

    registers.regs[0] = 0;  // enforce R0=0 after any write

    // Hardware IRQs stay latched while IRQs are disabled and are delivered
    // in vector priority order once the CPU can accept a maskable interrupt.
    if (registers.isInterruptEnabled()) {
        uint64_t pending_vector = Little64Vectors::kNoTrap;
        if (_selectHighestPriorityPendingInterrupt(pending_vector)) {
            _raiseInterrupt(pending_vector);
        }
    }

    for (Device* device : _devices) {
        if (device) {
            device->tick();
        }
    }

    _clock.tick();  // Advance virtual clock after all CPU and device activity
}

bool Little64CPU::_selectHighestPriorityPendingInterrupt(uint64_t& out_vector) const {
    const uint64_t pending_low = registers.interrupt_states & registers.interrupt_mask &
                                 Little64Vectors::validIrqMaskForBank(0);
    if (pending_low != 0) {
        out_vector = static_cast<uint64_t>(__builtin_ctzll(pending_low));
        return true;
    }

    const uint64_t pending_high = registers.interrupt_states_high & registers.interrupt_mask_high &
                                  Little64Vectors::validIrqMaskForBank(1);
    if (pending_high != 0) {
        out_vector = 64ULL + static_cast<uint64_t>(__builtin_ctzll(pending_high));
        return true;
    }

    return false;
}

bool Little64CPU::_isInterruptUnmasked(uint64_t vector) const {
    if (!Little64Vectors::isIrqVector(vector)) {
        return false;
    }

    const size_t bank = Little64Vectors::interruptBankForVector(vector);
    const uint64_t bit = Little64Vectors::interruptBitForVector(vector);
    if ((Little64Vectors::validIrqMaskForBank(bank) & bit) == 0) {
        return false;
    }

    if (bank == 0) {
        return (registers.interrupt_mask & bit) != 0;
    }
    if (bank == 1) {
        return (registers.interrupt_mask_high & bit) != 0;
    }
    return false;
}

bool Little64CPU::_setInterruptPending(uint64_t vector) {
    if (!Little64Vectors::isIrqVector(vector)) {
        return false;
    }

    const size_t bank = Little64Vectors::interruptBankForVector(vector);
    const uint64_t bit = Little64Vectors::interruptBitForVector(vector);
    if (bank == 0) {
        const bool was_pending = (registers.interrupt_states & bit) != 0;
        registers.interrupt_states |= bit;
        return !was_pending;
    } else if (bank == 1) {
        const bool was_pending = (registers.interrupt_states_high & bit) != 0;
        registers.interrupt_states_high |= bit;
        return !was_pending;
    }

    return false;
}

void Little64CPU::_clearInterruptPending(uint64_t vector) {
    if (!Little64Vectors::isIrqVector(vector)) {
        return;
    }

    const size_t bank = Little64Vectors::interruptBankForVector(vector);
    const uint64_t bit = Little64Vectors::interruptBitForVector(vector);
    if (bank == 0) {
        registers.interrupt_states &= ~bit;
    } else if (bank == 1) {
        registers.interrupt_states_high &= ~bit;
    }
}

void Little64CPU::assertInterrupt(uint64_t num) {
    if (_setInterruptPending(num)) {
        _recordBootEvent("irq-raise", num, registers.regs[15], registers.cpu_control);
    }
}

void Little64CPU::clearInterrupt(uint64_t num) {
    _clearInterruptPending(num);
}

void Little64CPU::dispatchInstruction(const Instruction& instr) {
    switch (instr.format) {
        case 0: _dispatchLSReg(instr);   break;
        case 1: _dispatchLSPCRel(instr); break;
        case 2: _dispatchLDI(instr);     break;
        case 3:
            if (instr.is_unconditional_jump) _dispatchUJMP(instr);
            else _dispatchGP(instr);
            break;
    }
}

// Flag bit positions
static constexpr uint64_t FLAG_ZERO  = 1 << 0;
static constexpr uint64_t FLAG_CARRY = 1 << 1;
static constexpr uint64_t FLAG_SIGN  = 1 << 2;

void Little64CPU::_updateFlags(uint64_t result, bool carry) {
    registers.flags = 0;
    if (result == 0)            registers.flags |= FLAG_ZERO;
    if (carry)                  registers.flags |= FLAG_CARRY;
    if (result >> 63)           registers.flags |= FLAG_SIGN;
}

static bool checkCondition(uint64_t flags, LS::Opcode op) {
    bool z = flags & FLAG_ZERO;
    bool c = flags & FLAG_CARRY;
    bool s = flags & FLAG_SIGN;
    switch (op) {
        case LS::Opcode::JUMP_Z:  return z;
        case LS::Opcode::JUMP_C:  return c;
        case LS::Opcode::JUMP_S:  return s;
        case LS::Opcode::JUMP_GT: return !z && !s;
        case LS::Opcode::JUMP_LT: return s;
        default: return false;
    }
}

void Little64CPU::_dispatchLSReg(const Instruction& instr) {
    const uint64_t op_pc = registers.regs[15] - 2;
    uint64_t addr = registers.regs[instr.rs1] + (instr.offset2 * 2);
    const bool trace_lr = _shouldTraceLrLsOp(instr, op_pc);
    const LS::Opcode op = static_cast<LS::Opcode>(instr.opcode_ls);

    if (trace_lr) {
        _recordBootEvent("lr-ls-pre", op_pc,
                         (static_cast<uint64_t>(instr.format) << 24) |
                         (static_cast<uint64_t>(instr.opcode_ls) << 16) |
                         (static_cast<uint64_t>(instr.rd) << 8) |
                         static_cast<uint64_t>(instr.rs1),
                         addr);
        _recordLrTraceRegs("lr-regs-pre", op_pc);
    }

    switch (op) {
        case LS::Opcode::LOAD:
            registers.regs[instr.rd] = _readMemory64(addr, op_pc);
            break;
        case LS::Opcode::STORE:
            _writeMemory64(addr, registers.regs[instr.rd], op_pc);
            break;
        case LS::Opcode::PUSH: {
            const uint64_t pushed_value = registers.regs[instr.rs1];
            registers.regs[instr.rd] -= 8;
            _writeMemory64(registers.regs[instr.rd], pushed_value, op_pc);
            if (trace_lr) {
                _recordBootEvent("lr-mem-write", registers.regs[instr.rd], pushed_value, op_pc);
            }
            break;
        }
        case LS::Opcode::POP: {
            const uint64_t pop_addr = registers.regs[instr.rd];
            const uint64_t popped_value = _readMemory64(pop_addr, op_pc);
            registers.regs[instr.rs1] = popped_value;
            registers.regs[instr.rd] += 8;
            if (trace_lr) {
                _recordBootEvent("lr-mem-read", pop_addr, popped_value, op_pc);
            }
            break;
        }
        case LS::Opcode::MOVE:
            registers.regs[instr.rd] = addr;
            break;
        case LS::Opcode::BYTE_LOAD:
            registers.regs[instr.rd] = _readMemory8(addr, op_pc);
            break;
        case LS::Opcode::BYTE_STORE:
            _writeMemory8(addr, registers.regs[instr.rd] & 0xFF, op_pc);
            break;
        case LS::Opcode::SHORT_LOAD:
            registers.regs[instr.rd] = _readMemory16(addr, op_pc);
            break;
        case LS::Opcode::SHORT_STORE:
            _writeMemory16(addr, registers.regs[instr.rd] & 0xFFFF, op_pc);
            break;
        case LS::Opcode::WORD_LOAD:
            registers.regs[instr.rd] = _readMemory32(addr, op_pc);
            break;
        case LS::Opcode::WORD_STORE:
            _writeMemory32(addr, registers.regs[instr.rd] & 0xFFFFFFFF, op_pc);
            break;
        case LS::Opcode::JUMP_Z:
        case LS::Opcode::JUMP_C:
        case LS::Opcode::JUMP_S:
        case LS::Opcode::JUMP_GT:
        case LS::Opcode::JUMP_LT:
            if (checkCondition(registers.flags, static_cast<LS::Opcode>(instr.opcode_ls)))
                registers.regs[instr.rd] = addr;
            break;
    }

    if (trace_lr) {
        _recordLrTraceRegs("lr-regs-post", op_pc);
        _recordBootEvent("lr-ls-post", op_pc,
                         (static_cast<uint64_t>(instr.format) << 24) |
                         (static_cast<uint64_t>(instr.opcode_ls) << 16) |
                         (static_cast<uint64_t>(instr.rd) << 8) |
                         static_cast<uint64_t>(instr.rs1),
                         addr);
    }
}

void Little64CPU::_dispatchLSPCRel(const Instruction& instr) {
    const uint64_t op_pc = registers.regs[15] - 2;
    // PC is already post-incremented; pc_rel is in instruction units (×2 bytes)
    uint64_t effective = registers.regs[15] + (static_cast<int64_t>(instr.pc_rel) * 2);
    const bool trace_lr = _shouldTraceLrLsOp(instr, op_pc);
    const LS::Opcode op = static_cast<LS::Opcode>(instr.opcode_ls);

    if (trace_lr) {
        _recordBootEvent("lr-ls-pre", op_pc,
                         (static_cast<uint64_t>(instr.format) << 24) |
                         (static_cast<uint64_t>(instr.opcode_ls) << 16) |
                         (static_cast<uint64_t>(instr.rd) << 8) |
                         static_cast<uint64_t>(instr.rs1),
                         effective);
        _recordLrTraceRegs("lr-regs-pre", op_pc);
    }

    switch (op) {
        case LS::Opcode::LOAD:
            registers.regs[instr.rd] = _readMemory64(effective, op_pc);
            break;
        case LS::Opcode::STORE:
            _writeMemory64(effective, registers.regs[instr.rd], op_pc);
            break;
        case LS::Opcode::PUSH: {
            uint64_t value = _readMemory64(effective, op_pc);
            registers.regs[instr.rd] -= 8;
            _writeMemory64(registers.regs[instr.rd], value, op_pc);
            if (trace_lr) {
                _recordBootEvent("lr-mem-write", registers.regs[instr.rd], value, op_pc);
            }
            break;
        }
        case LS::Opcode::POP: {
            const uint64_t pop_addr = registers.regs[instr.rd];
            uint64_t value = _readMemory64(pop_addr, op_pc);
            registers.regs[instr.rd] += 8;
            _writeMemory64(effective, value, op_pc);
            if (trace_lr) {
                _recordBootEvent("lr-mem-read", pop_addr, value, op_pc);
            }
            break;
        }
        case LS::Opcode::MOVE:
            registers.regs[instr.rd] = effective;
            break;
        case LS::Opcode::BYTE_LOAD:
            registers.regs[instr.rd] = _readMemory8(effective, op_pc);
            break;
        case LS::Opcode::BYTE_STORE:
            _writeMemory8(effective, registers.regs[instr.rd] & 0xFF, op_pc);
            break;
        case LS::Opcode::SHORT_LOAD:
            registers.regs[instr.rd] = _readMemory16(effective, op_pc);
            break;
        case LS::Opcode::SHORT_STORE:
            _writeMemory16(effective, registers.regs[instr.rd] & 0xFFFF, op_pc);
            break;
        case LS::Opcode::WORD_LOAD:
            registers.regs[instr.rd] = _readMemory32(effective, op_pc);
            break;
        case LS::Opcode::WORD_STORE:
            _writeMemory32(effective, registers.regs[instr.rd] & 0xFFFFFFFF, op_pc);
            break;
        case LS::Opcode::JUMP_Z:
        case LS::Opcode::JUMP_C:
        case LS::Opcode::JUMP_S:
        case LS::Opcode::JUMP_GT:
        case LS::Opcode::JUMP_LT: {
            // JUMP.* in Format 01 uses a 10-bit offset with implicit Rd = R15.
            // The effective address is recomputed here using the full bits[9:0].
            uint64_t jump_effective = registers.regs[15] + (static_cast<int64_t>(instr.pc_rel) * 2);
            if (checkCondition(registers.flags, static_cast<LS::Opcode>(instr.opcode_ls)))
                registers.regs[15] = jump_effective;
            break;
        }
    }

    if (trace_lr) {
        _recordLrTraceRegs("lr-regs-post", op_pc);
        _recordBootEvent("lr-ls-post", op_pc,
                         (static_cast<uint64_t>(instr.format) << 24) |
                         (static_cast<uint64_t>(instr.opcode_ls) << 16) |
                         (static_cast<uint64_t>(instr.rd) << 8) |
                         static_cast<uint64_t>(instr.rs1),
                         effective);
    }
}

void Little64CPU::_dispatchLDI(const Instruction& instr) {
    if (instr.shift == 0) {
        registers.regs[instr.rd] = instr.imm8;
    } else {
        registers.regs[instr.rd] |= (static_cast<uint64_t>(instr.imm8) << (instr.shift * 8));

        // If the shift is 3 and the immediate's MSB is set, sign-extend from bit 31 upward.
        if (instr.shift == 3 && (instr.imm8 & 0x80) != 0) {
            registers.regs[instr.rd] |= 0xFFFFFFFF00000000ULL;
        }
    }
}

void Little64CPU::_dispatchUJMP(const Instruction& instr) {
    registers.regs[15] = registers.regs[15] + (static_cast<int64_t>(instr.pc_rel) * 2);
}

void Little64CPU::_dispatchGP(const Instruction& instr) {
    uint64_t a = registers.regs[instr.rd];
    uint64_t b = registers.regs[instr.rs1];

    switch (static_cast<GP::Opcode>(instr.opcode_gp)) {
        case GP::Opcode::ADD: {
            uint64_t result = a + b;
            bool carry = result < a;
            _updateFlags(result, carry);
            registers.regs[instr.rd] = result;
            break;
        }
        case GP::Opcode::SUB: {
            uint64_t result = a - b;
            bool borrow = b > a;
            _updateFlags(result, borrow);
            registers.regs[instr.rd] = result;
            break;
        }
        case GP::Opcode::TEST: {
            uint64_t result = a - b;
            bool borrow = b > a;
            _updateFlags(result, borrow);
            // do not store result
            break;
        }

        case GP::Opcode::LLR: {
            // Load-Linked: read the value at Rs1 and set reservation
            uint64_t addr = b;  // rs1 is the address
            uint64_t value = _readMemory64(addr, registers.regs[15]);
            registers.regs[instr.rd] = value;

            // Set reservation for this address
            registers.ll_reservation_addr = addr;
            registers.ll_reservation_valid = true;
            break;
        }

        case GP::Opcode::SCR: {
            // Store-Conditional: conditionally store Rd to Rs1
            // Z flag: 1 if store succeeded (reservation valid), 0 if failed
            uint64_t addr = b;  // rs1 is the address
            uint64_t value = a;  // rd is the value to store

            if (registers.ll_reservation_valid && registers.ll_reservation_addr == addr) {
                // Reservation is valid, perform the store
                _writeMemory64(addr, value, registers.regs[15]);
                registers.ll_reservation_valid = false;  // clear reservation after successful store
                registers.flags |= FLAG_ZERO;  // set Z flag to indicate success
            } else {
                // Reservation is invalid or different address, store fails
                registers.ll_reservation_valid = false;
                registers.flags &= ~FLAG_ZERO;  // clear Z flag to indicate failure
            }
            break;
        }

        case GP::Opcode::AND: {
            uint64_t result = a & b;
            _updateFlags(result);
            registers.regs[instr.rd] = result;
            break;
        }
        case GP::Opcode::OR: {
            uint64_t result = a | b;
            _updateFlags(result);
            registers.regs[instr.rd] = result;
            break;
        }
        case GP::Opcode::XOR: {
            uint64_t result = a ^ b;
            _updateFlags(result);
            registers.regs[instr.rd] = result;
            break;
        }
        case GP::Opcode::SLL: {
            if (b == 0) { _updateFlags(a); registers.regs[instr.rd] = a; break; }
            if (b >= 64) { _updateFlags(0); registers.regs[instr.rd] = 0; break; }
            uint64_t result = a << b;
            bool carry = (a >> (64 - b)) != 0;
            _updateFlags(result, carry);
            registers.regs[instr.rd] = result;
            break;
        }
        case GP::Opcode::SRL: {
            if (b == 0) { _updateFlags(a); registers.regs[instr.rd] = a; break; }
            if (b >= 64) { _updateFlags(0); registers.regs[instr.rd] = 0; break; }
            uint64_t result = a >> b;
            bool carry = (a >> (b - 1)) & 1;
            _updateFlags(result, carry);
            registers.regs[instr.rd] = result;
            break;
        }
        case GP::Opcode::SRA: {
            if (b == 0) { _updateFlags(a); registers.regs[instr.rd] = a; break; }
            if (b >= 64) {
                uint64_t result = (int64_t(a) < 0) ? UINT64_MAX : 0;
                _updateFlags(result);
                registers.regs[instr.rd] = result;
                break;
            }
            uint64_t result = uint64_t(int64_t(a) >> b);
            bool carry = (a >> (b - 1)) & 1;
            _updateFlags(result, carry);
            registers.regs[instr.rd] = result;
            break;
        }

        case GP::Opcode::SLLI: {
            uint64_t imm = instr.rs1;  // 4-bit immediate, range 0–15
            if (imm == 0) { _updateFlags(a); registers.regs[instr.rd] = a; break; }
            uint64_t result = a << imm;
            bool carry = (a >> (64 - imm)) != 0;
            _updateFlags(result, carry);
            registers.regs[instr.rd] = result;
            break;
        }
        case GP::Opcode::SRLI: {
            uint64_t imm = instr.rs1;  // 4-bit immediate, range 0–15
            if (imm == 0) { _updateFlags(a); registers.regs[instr.rd] = a; break; }
            uint64_t result = a >> imm;
            bool carry = (a >> (imm - 1)) & 1;
            _updateFlags(result, carry);
            registers.regs[instr.rd] = result;
            break;
        }
        case GP::Opcode::SRAI: {
            uint64_t imm = instr.rs1;  // 4-bit immediate, range 0–15
            if (imm == 0) { _updateFlags(a); registers.regs[instr.rd] = a; break; }
            uint64_t result = uint64_t(int64_t(a) >> imm);
            bool carry = (a >> (imm - 1)) & 1;
            _updateFlags(result, carry);
            registers.regs[instr.rd] = result;
            break;
        }

        case GP::Opcode::SYSCALL: {
            // System call: user mode fires TRAP_SYSCALL, supervisor mode fires TRAP_SYSCALL_FROM_SUPERVISOR.
            uint64_t trap_num = registers.isUserMode()
                ? AddressTranslator::TRAP_SYSCALL
                : AddressTranslator::TRAP_SYSCALL_FROM_SUPERVISOR;
            registers.trap_pc = registers.regs[15] - 2;  // EPC points to the SYSCALL instruction
            registers.trap_cause = trap_num;
            _raiseInterrupt(trap_num, true, registers.regs[15] - 2);
            return;
        }

        case GP::Opcode::LSR: {
            const uint64_t selector = Little64SpecialRegisters::normalizeSelector(b);
            if (registers.isUserMode() && !Little64SpecialRegisters::isUserAccessibleSelector(selector)) {
                registers.trap_pc = registers.regs[15] - 2;
                registers.trap_cause = AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION;
                _raiseInterrupt(AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION, true, registers.regs[15] - 2);
                return;
            }
            registers.regs[instr.rd] = registers.getSpecialRegister(selector);
            break;
        }

        case GP::Opcode::SSR: {
            const uint64_t selector = Little64SpecialRegisters::normalizeSelector(b);
            if (registers.isUserMode() && !Little64SpecialRegisters::isUserAccessibleSelector(selector)) {
                registers.trap_pc = registers.regs[15] - 2;
                registers.trap_cause = AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION;
                _raiseInterrupt(AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION, true, registers.regs[15] - 2);
                return;
            }
            registers.setSpecialRegister(selector, a);
            // Flush TLB when paging config changes (page table root or cpu_control).
            if (selector == Little64SpecialRegisters::kCpuControl ||
                selector == Little64SpecialRegisters::kPageTableRootPhysical) {
                _flushTLB();
            }
            if (selector == Little64SpecialRegisters::kHypercallCaps) {
                _executeHypercall();
            }
            break;
        }

        case GP::Opcode::IRET: {
            if (registers.isUserMode()) {
                registers.trap_pc = registers.regs[15] - 2;
                registers.trap_cause = AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION;
                _raiseInterrupt(AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION, true, registers.regs[15] - 2);
                return;
            }
            registers.regs[15]   = registers.interrupt_epc;
            registers.flags      = registers.interrupt_eflags;
            registers.cpu_control = registers.interrupt_cpu_control;
            _flushTLB();  // cpu_control may change paging/privilege state
            break;
        }

        case GP::Opcode::STOP: {
            if (registers.isUserMode()) {
                registers.trap_pc = registers.regs[15] - 2;
                registers.trap_cause = AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION;
                _raiseInterrupt(AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION, true, registers.regs[15] - 2);
                return;
            }
            _recordBootEvent("stop", registers.regs[15], registers.flags, registers.cpu_control);
            std::cerr << "STOP instruction hit. Register state:" << std::endl;
            for (int i = 0; i < 16; ++i) {
                std::cerr << "  R" << i << ": 0x" << std::hex << registers.regs[i] << std::dec << std::endl;
            }
            isRunning = false;
            _dumpBootEvents("STOP instruction");
            break;
        }
        default: {
            registers.trap_pc = registers.regs[15] - 2;
            registers.trap_cause = AddressTranslator::TRAP_INVALID_INSTRUCTION;
            _recordBootEvent("invalid-instruction", registers.trap_pc, instr.encode(), 0);
            _raiseInterrupt(AddressTranslator::TRAP_INVALID_INSTRUCTION, true, registers.regs[15] - 2);
            return;
        }
    }
}

Little64CPU::TranslationResult Little64CPU::_translateAddress(uint64_t virtual_addr, CpuAccessType access) const {
    PagingAccessType paging_access = PagingAccessType::Read;
    switch (access) {
        case CpuAccessType::Read: paging_access = PagingAccessType::Read; break;
        case CpuAccessType::Write: paging_access = PagingAccessType::Write; break;
        case CpuAccessType::Execute: paging_access = PagingAccessType::Execute; break;
    }

    const PagingConfig cfg{
        .enabled = registers.isPagingEnabled(),
        .root_table_physical = registers.page_table_root_physical,
        .is_user = registers.isUserMode(),
    };
    const PagingTranslateResult translated = _translator.translate(_bus, cfg, virtual_addr, paging_access);
    return TranslationResult{
        .valid = translated.valid,
        .physical = translated.physical,
        .trap_cause = translated.trap_cause,
        .trap_aux = translated.trap_aux,
    };
}

bool Little64CPU::_mapAddressSlowPath(uint64_t virtual_addr, CpuAccessType access, uint64_t operation_pc, uint64_t& physical_out) {
    const TranslationResult result = _translateAddress(virtual_addr, access);
    if (result.valid) {
        physical_out = result.physical;

        // Populate TLB on successful translation.
        if (registers.isPagingEnabled()) {
            const uint64_t vpage = virtual_addr >> 12;
            const size_t idx = vpage & kTLBMask;
            TLBEntry& entry = _tlb[idx];
            const uint8_t access_bit = 1u << static_cast<uint8_t>(access);
            if (entry.vpage == vpage) {
                // Same page -- accumulate permission bits.
                entry.perms |= access_bit;
            } else {
                // Different page -- replace entry.
                entry.vpage = vpage;
                entry.pbase = result.physical & ~0xFFFULL;
                entry.perms = access_bit;
                entry.user_accessible = registers.isUserMode();
            }
        }
        return true;
    }

    registers.trap_cause = result.trap_cause;
    registers.trap_fault_addr = virtual_addr;
    registers.trap_access = static_cast<uint64_t>(access);
    registers.trap_pc = operation_pc;
    registers.trap_aux = result.trap_aux;

    _recordBootEvent("mmu-fault",
                     virtual_addr,
                     (static_cast<uint64_t>(access) << 56) | (result.trap_cause & 0x00FFFFFFFFFFFFFFULL),
                     operation_pc);
    _recordBootEvent("mmu-fault-detail", result.trap_cause, result.trap_aux, registers.page_table_root_physical);

    _raiseInterrupt(result.trap_cause, true, operation_pc);
    return false;
}

bool Little64CPU::_allocatePageTablePage(uint64_t& out_page) {
    constexpr uint64_t PAGE = 4096;
    if (_mem_size < PAGE || _page_table_alloc_cursor < (_mem_base + PAGE)) {
        return false;
    }

    _page_table_alloc_cursor -= PAGE;
    if (_page_table_alloc_cursor < _mem_base || _page_table_alloc_cursor + PAGE > _mem_base + _mem_size) {
        return false;
    }

    out_page = _page_table_alloc_cursor;
    for (uint64_t off = 0; off < PAGE; off += 8) {
        _bus.write64(out_page + off, 0, MemoryAccessType::Write);
    }
    return true;
}

void Little64CPU::_executeHypercall() {
    const uint64_t service = registers.regs[1];
    registers.regs[1] = HYPERCALL_STATUS_UNSUPPORTED;

    switch (service) {
        case HYPERCALL_MEMINFO:
            registers.regs[1] = HYPERCALL_STATUS_OK;
            registers.regs[2] = _mem_base;
            registers.regs[3] = _mem_size;
            registers.regs[4] = SERIAL_BASE;
            registers.regs[5] = HYPERCALL_CAP_MINIMAL_BOOT;
            break;
        case HYPERCALL_GET_BOOT_SOURCE_INFO:
            if (registers.regs[2] != 0) {
                registers.regs[1] = HYPERCALL_STATUS_INVALID;
                break;
            }
            registers.regs[1] = HYPERCALL_STATUS_OK;
            registers.regs[2] = 1; // paged source
            registers.regs[3] = registers.boot_source_page_size;
            registers.regs[4] = registers.boot_source_page_count;
            registers.regs[5] = 0;
            break;
        case HYPERCALL_READ_BOOT_SOURCE_PAGES: {
            const uint64_t start_page = registers.regs[2];
            const uint64_t page_count = registers.regs[3];
            const uint64_t dst_phys = registers.regs[4];
            const uint64_t source_selector = registers.regs[5];

            if (source_selector != 0 || registers.boot_source_page_size == 0) {
                registers.regs[1] = HYPERCALL_STATUS_INVALID;
                break;
            }

            const uint64_t page_size = registers.boot_source_page_size;
            const uint64_t total_pages = registers.boot_source_page_count;
            if (start_page >= total_pages || page_count == 0 || start_page + page_count > total_pages) {
                registers.regs[1] = HYPERCALL_STATUS_RANGE;
                registers.regs[2] = 0;
                break;
            }

            uint64_t copied_pages = 0;
            for (uint64_t p = 0; p < page_count; ++p) {
                const uint64_t source_page = start_page + p;
                const uint64_t source_off = source_page * page_size;
                const uint64_t dest_off = dst_phys + p * page_size;

                for (uint64_t i = 0; i < page_size; ++i) {
                    const uint64_t index = source_off + i;
                    if (index >= _boot_source_bytes.size()) {
                        break;
                    }
                    _bus.write8(dest_off + i, _boot_source_bytes[static_cast<size_t>(index)], MemoryAccessType::Write);
                }
                ++copied_pages;
            }

            registers.regs[1] = HYPERCALL_STATUS_OK;
            registers.regs[2] = copied_pages;
            break;
        }
        default:
            registers.regs[1] = HYPERCALL_STATUS_UNSUPPORTED;
            break;
    }
}

void Little64CPU::_invalidateReservationOnWrite(uint64_t addr, size_t width) {
    if (!registers.ll_reservation_valid || width == 0) {
        return;
    }

    constexpr uint64_t kReservationWidth = 8;
    const uint64_t reservation_start = registers.ll_reservation_addr;
    const uint64_t reservation_end = reservation_start > UINT64_MAX - (kReservationWidth - 1)
        ? UINT64_MAX
        : reservation_start + (kReservationWidth - 1);
    const uint64_t write_end = addr > UINT64_MAX - (static_cast<uint64_t>(width) - 1)
        ? UINT64_MAX
        : addr + (static_cast<uint64_t>(width) - 1);

    if (addr <= reservation_end && reservation_start <= write_end) {
        registers.ll_reservation_valid = false;
    }
}

uint8_t Little64CPU::_readMemory8(uint64_t addr, uint64_t operation_pc, CpuAccessType access) {
    uint64_t physical = 0;
    if (!_mapAddress(addr, access, operation_pc, physical)) {
        return 0xFF;
    }
    return _bus.read8(physical, access == CpuAccessType::Execute ? MemoryAccessType::Execute : MemoryAccessType::Read);
}

void Little64CPU::_writeMemory8(uint64_t addr, uint8_t v, uint64_t operation_pc) {
    uint64_t physical = 0;
    if (!_mapAddress(addr, CpuAccessType::Write, operation_pc, physical)) {
        return;
    }
    if (_isWatchAddrInRange(addr)) {
        _recordBootEvent("watch-write8", addr, static_cast<uint64_t>(v), operation_pc);
        _recordBootEvent("watch-regs", registers.regs[11], registers.regs[12], registers.regs[13]);
    }
    _bus.write8(physical, v, MemoryAccessType::Write);
    _invalidateReservationOnWrite(addr, 1);
    if (physical == SERIAL_BASE) {
        _recordBootEvent("uart-tx", static_cast<uint64_t>(v), addr, operation_pc);
    }
}

uint16_t Little64CPU::_readMemory16(uint64_t addr, uint64_t operation_pc, CpuAccessType access) {
    uint64_t physical = 0;
    if (!_mapAddress(addr, access, operation_pc, physical)) {
        return 0xFFFF;
    }
    return _bus.read16(physical, access == CpuAccessType::Execute ? MemoryAccessType::Execute : MemoryAccessType::Read);
}

void Little64CPU::_writeMemory16(uint64_t addr, uint16_t v, uint64_t operation_pc) {
    uint64_t physical = 0;
    if (!_mapAddress(addr, CpuAccessType::Write, operation_pc, physical)) {
        return;
    }
    if (_isWatchAddrInRange(addr)) {
        _recordBootEvent("watch-write16", addr, static_cast<uint64_t>(v), operation_pc);
        _recordBootEvent("watch-regs", registers.regs[11], registers.regs[12], registers.regs[13]);
    }
    _bus.write16(physical, v, MemoryAccessType::Write);
    _invalidateReservationOnWrite(addr, 2);
}

uint32_t Little64CPU::_readMemory32(uint64_t addr, uint64_t operation_pc, CpuAccessType access) {
    uint64_t physical = 0;
    if (!_mapAddress(addr, access, operation_pc, physical)) {
        return 0xFFFFFFFFu;
    }
    return _bus.read32(physical, access == CpuAccessType::Execute ? MemoryAccessType::Execute : MemoryAccessType::Read);
}

void Little64CPU::_writeMemory32(uint64_t addr, uint32_t v, uint64_t operation_pc) {
    uint64_t physical = 0;
    if (!_mapAddress(addr, CpuAccessType::Write, operation_pc, physical)) {
        return;
    }
    if (_isWatchAddrInRange(addr)) {
        _recordBootEvent("watch-write32", addr, static_cast<uint64_t>(v), operation_pc);
        _recordBootEvent("watch-regs", registers.regs[11], registers.regs[12], registers.regs[13]);
    }
    _bus.write32(physical, v, MemoryAccessType::Write);
    _invalidateReservationOnWrite(addr, 4);
}

uint64_t Little64CPU::_readMemory64(uint64_t addr, uint64_t operation_pc, CpuAccessType access) {
    uint64_t physical = 0;
    if (!_mapAddress(addr, access, operation_pc, physical)) {
        return UINT64_MAX;
    }
    return _bus.read64(physical, access == CpuAccessType::Execute ? MemoryAccessType::Execute : MemoryAccessType::Read);
}

void Little64CPU::_writeMemory64(uint64_t addr, uint64_t v, uint64_t operation_pc) {
    uint64_t physical = 0;
    if (!_mapAddress(addr, CpuAccessType::Write, operation_pc, physical)) {
        return;
    }
    if (_isWatchAddrInRange(addr)) {
        _recordBootEvent("watch-write64", addr, v, operation_pc);
        _recordBootEvent("watch-regs", registers.regs[11], registers.regs[12], registers.regs[13]);
    }
    _bus.write64(physical, v, MemoryAccessType::Write);
    _invalidateReservationOnWrite(addr, 8);
}

bool Little64CPU::loadProgramElf(const std::vector<uint8_t>& elf_bytes, uint64_t /*base_unused*/) {
    _boot_event_head = 0;
    _boot_event_wrapped = false;
    _boot_event_dumped = false;
    _cycle_count = 0;
    _flushTLB();
    if (elf_bytes.size() < sizeof(Elf64_Ehdr))
        return false;

    const Elf64_Ehdr* ehdr = reinterpret_cast<const Elf64_Ehdr*>(elf_bytes.data());
    if (ehdr->e_ident[EI_MAG0] != ELFMAG0 || ehdr->e_ident[EI_MAG1] != ELFMAG1 ||
        ehdr->e_ident[EI_MAG2] != ELFMAG2 || ehdr->e_ident[EI_MAG3] != ELFMAG3) {
        return false;
    }
    if (ehdr->e_ident[EI_CLASS] != ELFCLASS64 || ehdr->e_ident[EI_DATA] != ELFDATA2LSB)
        return false;
    if (ehdr->e_machine != 0x4C36) // EM_LITTLE64
        return false;
    if (ehdr->e_phoff + ehdr->e_phnum * ehdr->e_phentsize > elf_bytes.size())
        return false;

    uint64_t min_addr = UINT64_MAX;
    uint64_t max_addr = 0;
    bool found_load = false;

    for (uint16_t i = 0; i < ehdr->e_phnum; ++i) {
        const Elf64_Phdr* ph = reinterpret_cast<const Elf64_Phdr*>(
            elf_bytes.data() + ehdr->e_phoff + i * ehdr->e_phentsize);
        if (ph->p_type != PT_LOAD) continue;
        min_addr = std::min(min_addr, ph->p_vaddr);
        max_addr = std::max(max_addr, ph->p_vaddr + ph->p_memsz);
        found_load = true;
    }

    if (!found_load) return false;

    // Align min_addr down to page boundary
    constexpr uint64_t PAGE = 4096;
    uint64_t base_addr = (min_addr / PAGE) * PAGE;
    uint64_t alloc_size = ((max_addr - base_addr + PAGE - 1) / PAGE) * PAGE;

    std::vector<uint8_t> ram_bytes(alloc_size, 0);

    for (uint16_t i = 0; i < ehdr->e_phnum; ++i) {
        const Elf64_Phdr* ph = reinterpret_cast<const Elf64_Phdr*>(
            elf_bytes.data() + ehdr->e_phoff + i * ehdr->e_phentsize);
        if (ph->p_type != PT_LOAD) continue;
        
        uint64_t offset_in_ram = ph->p_vaddr - base_addr;
        std::memcpy(ram_bytes.data() + offset_in_ram,
                    elf_bytes.data() + ph->p_offset,
                    static_cast<size_t>(ph->p_filesz));
    }

    constexpr uint64_t RAM_EXTRA = 64 * 1024 * 1024;
    uint64_t total_ram = alloc_size + RAM_EXTRA;

     MachineConfig cfg;
     cfg.addPreloadedRam(base_addr, std::move(ram_bytes), total_ram, "MEM")
         .addSerial(SERIAL_BASE, "SERIAL")
         .addTimer(TIMER_BASE, "TIMER");
     if (_disk_image && _disk_image->isValid()) {
         cfg.addPvBlock(PVBLK_BASE, _disk_image->path(), _disk_image->isReadOnly(), "PVBLK");
     }
     cfg.applyTo(_bus, _devices, this, &_clock);

    _mem_base = base_addr;
    _mem_size = total_ram;
    _page_table_alloc_cursor = _mem_base + _mem_size;

    registers = {};
    registers.boot_source_page_size = 4096;
    registers.boot_source_page_count = (_boot_source_bytes.size() + 4095ULL) / 4096ULL;
    registers.hypercall_caps = HYPERCALL_CAP_MINIMAL_BOOT;
    registers.regs[13] = base_addr + total_ram - 8;
    registers.regs[15] = ehdr->e_entry;
    isRunning = true;
    _recordBootEvent("elf-load", base_addr, total_ram, ehdr->e_entry);

    return true;
}

void Little64CPU::loadProgram(const std::vector<uint16_t>& words, uint64_t base, uint64_t entry_offset) {
    _boot_event_head = 0;
    _boot_event_wrapped = false;
    _boot_event_dumped = false;
    _cycle_count = 0;
    _flushTLB();
    // Convert 16-bit words to bytes (little-endian)
    std::vector<uint8_t> bytes;
    bytes.reserve(words.size() * 2);
    for (uint16_t w : words) {
        bytes.push_back(w & 0xFF);
        bytes.push_back((w >> 8) & 0xFF);
    }

    // Round the program image up to a 4K page so the RAM starts on a clean boundary.
    constexpr uint64_t PAGE = 4096;
    uint64_t prog_size = (bytes.size() + PAGE - 1) / PAGE * PAGE;
    if (prog_size == 0) prog_size = PAGE;

    // Use a single writable RAM region that covers both the program image and the
    // working RAM.  A separate RomRegion would silently discard writes to .data /
    // .bss, breaking any C/C++ program that modifies global or static variables.
    constexpr uint64_t RAM_SIZE    = 64 * 1024 * 1024;  // 64 MB
    uint64_t total_size = prog_size + RAM_SIZE;

     MachineConfig cfg;
     cfg.addPreloadedRam(base, std::move(bytes), total_size, "MEM")
         .addSerial(SERIAL_BASE, "SERIAL")
         .addTimer(TIMER_BASE, "TIMER");
     if (_disk_image && _disk_image->isValid()) {
         cfg.addPvBlock(PVBLK_BASE, _disk_image->path(), _disk_image->isReadOnly(), "PVBLK");
     }
     cfg.applyTo(_bus, _devices, this, &_clock);

    _mem_base = base;
    _mem_size = total_size;
    _page_table_alloc_cursor = _mem_base + _mem_size;

    // Reset CPU state.
    registers = {};
    registers.boot_source_page_size = 4096;
    registers.boot_source_page_count = (_boot_source_bytes.size() + 4095ULL) / 4096ULL;
    registers.hypercall_caps = HYPERCALL_CAP_MINIMAL_BOOT;
    // R13 is the stack pointer.  Initialise it to the top of the memory region
    // (stacks grow downward) so that C/C++ function prologues work correctly.
    registers.regs[13] = base + total_size - 8;
    registers.regs[15] = base + entry_offset;
    isRunning = true;
    _recordBootEvent("bin-load", base, total_size, registers.regs[15]);
}

bool Little64CPU::loadProgramElfDirectPaged(const std::vector<uint8_t>& elf_bytes,
                                            uint64_t kernel_physical_base,
                                            uint64_t direct_map_virtual_base,
                                            const std::vector<uint8_t>* dtb_override,
                                            uint64_t stack_top_reserve_bytes) {
    (void)direct_map_virtual_base;
    _boot_event_head = 0;
    _boot_event_wrapped = false;
    _boot_event_dumped = false;
    _cycle_count = 0;
    _flushTLB();
    if (elf_bytes.size() < sizeof(Elf64_Ehdr)) {
        return false;
    }

    const Elf64_Ehdr* ehdr = reinterpret_cast<const Elf64_Ehdr*>(elf_bytes.data());
    if (ehdr->e_ident[EI_MAG0] != ELFMAG0 || ehdr->e_ident[EI_MAG1] != ELFMAG1 ||
        ehdr->e_ident[EI_MAG2] != ELFMAG2 || ehdr->e_ident[EI_MAG3] != ELFMAG3) {
        return false;
    }
    if (ehdr->e_ident[EI_CLASS] != ELFCLASS64 || ehdr->e_ident[EI_DATA] != ELFDATA2LSB) {
        return false;
    }
    if (ehdr->e_machine != EM_LITTLE64) {
        return false;
    }
    if (ehdr->e_phoff + static_cast<uint64_t>(ehdr->e_phnum) * ehdr->e_phentsize > elf_bytes.size()) {
        return false;
    }

    uint64_t min_vaddr = UINT64_MAX;
    uint64_t max_vaddr = 0;
    bool found_load = false;
    for (uint16_t i = 0; i < ehdr->e_phnum; ++i) {
        const Elf64_Phdr* ph = reinterpret_cast<const Elf64_Phdr*>(
            elf_bytes.data() + ehdr->e_phoff + static_cast<uint64_t>(i) * ehdr->e_phentsize);
        if (ph->p_type != PT_LOAD) continue;
        min_vaddr = std::min(min_vaddr, ph->p_vaddr);
        max_vaddr = std::max(max_vaddr, ph->p_vaddr + ph->p_memsz);
        found_load = true;
    }
    if (!found_load) {
        return false;
    }

    constexpr uint64_t PAGE = 4096;
    const uint64_t virt_base = (min_vaddr / PAGE) * PAGE;
    const uint64_t image_span = ((max_vaddr - virt_base + PAGE - 1) / PAGE) * PAGE;

    std::vector<uint8_t> ram_bytes(static_cast<size_t>(image_span), 0);
    for (uint16_t i = 0; i < ehdr->e_phnum; ++i) {
        const Elf64_Phdr* ph = reinterpret_cast<const Elf64_Phdr*>(
            elf_bytes.data() + ehdr->e_phoff + static_cast<uint64_t>(i) * ehdr->e_phentsize);
        if (ph->p_type != PT_LOAD) continue;
        const uint64_t off = ph->p_vaddr - virt_base;
        if (off + ph->p_filesz > ram_bytes.size() || ph->p_offset + ph->p_filesz > elf_bytes.size()) {
            return false;
        }
        std::memcpy(ram_bytes.data() + off, elf_bytes.data() + ph->p_offset, static_cast<size_t>(ph->p_filesz));
    }

    const uint64_t total_ram = LITEX_BOOTROM_RAM_SIZE;
    if (image_span > total_ram) {
        return false;
    }

    std::vector<uint8_t> bootrom_window(static_cast<size_t>(LITEX_BOOTROM_SIZE), 0x00);
    std::vector<uint8_t> flash_window(static_cast<size_t>(LITEX_FLASH_WINDOW_SIZE), 0xFF);
    const std::string disk_path = (_disk_image && _disk_image->isValid()) ? _disk_image->path() : std::string();
    const bool disk_read_only = !_disk_image || _disk_image->isReadOnly();

    MachineConfig cfg;
    cfg.addRom(LITEX_BOOTROM_BASE, std::move(bootrom_window), "BOOTROM")
        .addRom(LITEX_FLASH_BASE, std::move(flash_window), "FLASH")
        .addRam(LITEX_SRAM_BASE, LITEX_SRAM_SIZE, "SRAM")
        .addPreloadedRam(kernel_physical_base, std::move(ram_bytes), total_ram, "RAM")
        .addLiteDramDfiiStub(LITEX_SDRAM_CSR_BASE, "LITEDRAM")
        .addLiteSdCard(LITEX_SDCARD_BASE, disk_path, disk_read_only, "LITESDCARD")
        .addLiteUart(LITEX_BOOTROM_SD_UART_BASE, "LITEUART")
        .addTimer(TIMER_BASE, "TIMER");
    cfg.applyTo(_bus, _devices, this, &_clock);

    _mem_base = kernel_physical_base;
    _mem_size = total_ram;
    _page_table_alloc_cursor = _mem_base + _mem_size;

    registers = {};
    registers.boot_source_page_size = 4096;
    registers.boot_source_page_count = (_boot_source_bytes.size() + 4095ULL) / 4096ULL;
    registers.hypercall_caps = HYPERCALL_CAP_MINIMAL_BOOT;

    // Place embedded DTB at a 4KB-aligned offset after the kernel image and
    // after a conservative early-boot scratch gap.
    //
    // head.S allocates three pages immediately after __bss_stop for:
    //   - L2 root
    //   - L1 kernel map
    //   - L1 identity map
    // The loader leaves a larger guard gap than the current minimum so small
    // future head.S scratch additions do not silently overlap the DTB.
    constexpr uint64_t EARLY_PT_SCRATCH_PAGES = 30;
    const uint64_t early_pt_scratch_bytes = EARLY_PT_SCRATCH_PAGES * PAGE;
    const uint64_t dtb_offset = (image_span + early_pt_scratch_bytes + 0xFFFULL) & ~0xFFFULL;
    const uint64_t dtb_phys = kernel_physical_base + dtb_offset;
    std::vector<uint8_t> dtb_fallback;
    auto dtb_span = DTBLoader::getEmbeddedDTB();
    if (dtb_override != nullptr) {
        dtb_fallback = *dtb_override;
        dtb_span = std::span<const uint8_t>(dtb_fallback.data(), dtb_fallback.size());
    }
    if (!dtb_span.empty() && dtb_phys + dtb_span.size() <= kernel_physical_base + total_ram) {
        for (size_t i = 0; i < dtb_span.size(); ++i) {
            _bus.write8(dtb_phys + i, dtb_span[i]);
        }
    }

    uint64_t entry_physical = 0;
    const uint64_t entry = ehdr->e_entry;
    const uint64_t virt_end = virt_base + image_span;

    // Accept both common kernel image styles:
    // 1) virtual entry inside PT_LOAD virtual window, or
    // 2) already-physical entry inside loaded physical image.
    if (entry >= virt_base && entry < virt_end) {
        entry_physical = kernel_physical_base + (entry - virt_base);
    } else if (entry >= kernel_physical_base && entry < kernel_physical_base + image_span) {
        entry_physical = entry;
    } else {
        return false;
    }

    // Linux-compatible boot handoff contract:
    //   R1  = physical address of device tree blob
    //   R13 = top of physical RAM (temporary early stack)
    //   R15 = physical address of _start
    //   Paging OFF, interrupts disabled, supervisor mode
    //
    // The kernel's head.S will set up page tables and enable paging.
    if (stack_top_reserve_bytes > total_ram) {
        return false;
    }
    registers.regs[1]  = dtb_phys;
    registers.regs[13] = kernel_physical_base + total_ram - stack_top_reserve_bytes - 8;
    registers.regs[15] = entry_physical;
    registers.boot_info_frame_physical = dtb_phys;  // SR12: for compatibility
    isRunning = true;
    _clock.resume();  // Start the virtual clock so timer devices can fire
    _recordBootEvent("direct-boot-load", kernel_physical_base, total_ram, entry_physical);
    _recordBootEvent("direct-boot-dtb", dtb_phys, static_cast<uint64_t>(dtb_span.size()), registers.regs[1]);
    if (_disk_image && _disk_image->isValid()) {
        _recordBootEvent("litex-sd-attach", LITEX_SDCARD_BASE, _disk_image->sectorCount(),
                         LITEX_BOOTROM_SD_UART_BASE);
    }
    return true;
}

bool Little64CPU::loadProgramLiteXFlashImage(const std::vector<uint8_t>& flash_bytes) {
    _boot_event_head = 0;
    _boot_event_wrapped = false;
    _boot_event_dumped = false;
    _cycle_count = 0;
    _flushTLB();

    if (flash_bytes.empty() || flash_bytes.size() > LITEX_FLASH_WINDOW_SIZE) {
        return false;
    }

    std::vector<uint8_t> flash_window(static_cast<size_t>(LITEX_FLASH_WINDOW_SIZE), 0xFF);
    std::memcpy(flash_window.data(), flash_bytes.data(), flash_bytes.size());
    setBootSourcePages(flash_bytes, 4096);

    MachineConfig cfg;
    cfg.addRam(0, LITEX_FLASH_RAM_SIZE, "RAM")
        .addRam(LITEX_SRAM_BASE, LITEX_SRAM_SIZE, "SRAM")
        .addRom(LITEX_FLASH_BASE, std::move(flash_window), "FLASH");
    if (_disk_image && _disk_image->isValid()) {
        cfg.addLiteSdCard(LITEX_SDCARD_BASE, _disk_image->path(), _disk_image->isReadOnly(), "LITESDCARD")
            .addLiteUart(LITEX_FLASH_SD_UART_BASE, "LITEUART");
    } else {
        cfg.addLiteUart(LITEX_UART_BASE, "LITEUART");
    }
    cfg.addTimer(TIMER_BASE, "TIMER");
    cfg.applyTo(_bus, _devices, this, &_clock);

    _mem_base = 0;
    _mem_size = LITEX_FLASH_RAM_SIZE;
    _page_table_alloc_cursor = _mem_base + _mem_size;

    registers = {};
    registers.boot_source_page_size = 4096;
    registers.boot_source_page_count = (_boot_source_bytes.size() + 4095ULL) / 4096ULL;
    registers.hypercall_caps = HYPERCALL_CAP_MINIMAL_BOOT;
    registers.regs[15] = LITEX_FLASH_BASE;
    isRunning = true;
    _clock.resume();
    _recordBootEvent("litex-flash-load", LITEX_FLASH_BASE, LITEX_FLASH_WINDOW_SIZE,
                     static_cast<uint64_t>(flash_bytes.size()));
    if (_disk_image && _disk_image->isValid()) {
        _recordBootEvent("litex-sd-attach", LITEX_SDCARD_BASE, _disk_image->sectorCount(),
                         LITEX_FLASH_SD_UART_BASE);
    }
    return true;
}

bool Little64CPU::loadProgramLiteXBootRomImage(const std::vector<uint8_t>& bootrom_bytes) {
    _boot_event_head = 0;
    _boot_event_wrapped = false;
    _boot_event_dumped = false;
    _cycle_count = 0;
    _flushTLB();

    if (bootrom_bytes.empty() || bootrom_bytes.size() > LITEX_BOOTROM_SIZE) {
        return false;
    }

    std::vector<uint8_t> bootrom_window(static_cast<size_t>(LITEX_BOOTROM_SIZE), 0x00);
    std::memcpy(bootrom_window.data(), bootrom_bytes.data(), bootrom_bytes.size());
    std::vector<uint8_t> flash_window(static_cast<size_t>(LITEX_FLASH_WINDOW_SIZE), 0xFF);
    setBootSourcePages(bootrom_bytes, 4096);

    MachineConfig cfg;
    cfg.addRom(LITEX_BOOTROM_BASE, std::move(bootrom_window), "BOOTROM")
        .addRom(LITEX_FLASH_BASE, std::move(flash_window), "FLASH")
        .addRam(LITEX_SRAM_BASE, LITEX_SRAM_SIZE, "SRAM")
        .addRam(LITEX_BOOTROM_RAM_BASE, LITEX_BOOTROM_RAM_SIZE, "RAM")
        .addLiteDramDfiiStub(LITEX_SDRAM_CSR_BASE, "LITEDRAM");
    if (_disk_image && _disk_image->isValid()) {
        cfg.addLiteSdCard(LITEX_SDCARD_BASE, _disk_image->path(), _disk_image->isReadOnly(), "LITESDCARD")
            .addLiteUart(LITEX_BOOTROM_SD_UART_BASE, "LITEUART");
    } else {
        cfg.addLiteUart(LITEX_UART_BASE, "LITEUART");
    }
    cfg.addTimer(TIMER_BASE, "TIMER");
    cfg.applyTo(_bus, _devices, this, &_clock);

    _mem_base = LITEX_BOOTROM_RAM_BASE;
    _mem_size = LITEX_BOOTROM_RAM_SIZE;
    _page_table_alloc_cursor = _mem_base + _mem_size;

    registers = {};
    registers.boot_source_page_size = 4096;
    registers.boot_source_page_count = (_boot_source_bytes.size() + 4095ULL) / 4096ULL;
    registers.hypercall_caps = HYPERCALL_CAP_MINIMAL_BOOT;
    registers.regs[15] = LITEX_BOOTROM_BASE;
    isRunning = true;
    _clock.resume();
    _recordBootEvent("litex-bootrom-load", LITEX_BOOTROM_BASE, LITEX_BOOTROM_SIZE,
                     static_cast<uint64_t>(bootrom_bytes.size()));
    if (_disk_image && _disk_image->isValid()) {
        _recordBootEvent("litex-sd-attach", LITEX_SDCARD_BASE, _disk_image->sectorCount(),
                         LITEX_BOOTROM_SD_UART_BASE);
    }
    return true;
}

void Little64CPU::setBootSourcePages(std::vector<uint8_t> bytes, uint64_t page_size) {
    _boot_source_bytes = std::move(bytes);
    registers.boot_source_page_size = page_size;
    if (page_size == 0) {
        registers.boot_source_page_count = 0;
    } else {
        registers.boot_source_page_count = (static_cast<uint64_t>(_boot_source_bytes.size()) + page_size - 1) / page_size;
    }
}

SerialDevice* Little64CPU::getSerial() {
    for (Device* d : _devices) {
        if (auto* s = dynamic_cast<SerialDevice*>(d))
            return s;
    }
    return nullptr;
}

std::string Little64CPU::takeConsoleOutput() {
    for (Device* d : _devices) {
        if (auto* serial = dynamic_cast<SerialDevice*>(d)) {
            std::string output = serial->txBuffer();
            if (!output.empty()) {
                serial->clearTxBuffer();
            }
            return output;
        }
        if (auto* liteuart = dynamic_cast<LiteUartDevice*>(d)) {
            std::string output = liteuart->txBuffer();
            if (!output.empty()) {
                liteuart->clearTxBuffer();
            }
            return output;
        }
    }
    return {};
}

void Little64CPU::setMmioTrace(bool enabled) {
    for (Device* d : _devices) {
        if (d) {
            d->setMmioTrace(enabled);
        }
    }
}

void Little64CPU::setControlFlowTrace(bool enabled) {
    _trace_control_flow = enabled;
    _updateAnyTraceActive();
}

void Little64CPU::dumpBootLog(const char* reason) {
    _dumpBootEvents(reason);
    if (_trace_writer) {
        _trace_writer->flush();
        _trace_writer->printStats();
    }
}

bool Little64CPU::setBootEventOutputFile(const std::string& path) {
    TraceWriter::Config config;
    config.path = path;
    auto writer = std::make_unique<TraceWriter>(std::move(config));
    if (!writer->open()) {
        return false;
    }
    _trace_writer = std::move(writer);
    return true;
}

bool Little64CPU::setTraceWriter(std::unique_ptr<TraceWriter> writer) {
    if (!writer || !writer->isOpen()) {
        return false;
    }
    _trace_writer = std::move(writer);
    return true;
}

bool Little64CPU::dumpBootLogToFile(const char* reason, const std::string& path) const {
    std::ofstream out(path, std::ios::out | std::ios::trunc);
    if (!out.is_open()) {
        return false;
    }
    _writeBootEvents(out, reason);
    return static_cast<bool>(out);
}

bool Little64CPU::_raiseInterrupt(uint64_t interrupt_number, bool exception, uint64_t epc) {
    if (exception) {
        _recordBootEvent("exception-raise", interrupt_number, epc, registers.regs[15]);
    }
    if (!exception) {
        if (!Little64Vectors::isIrqVector(interrupt_number)) {
            return false;
        }
        if (!registers.isInterruptEnabled()) {
            return false;
        }
        if (!_isInterruptUnmasked(interrupt_number)) {
            return false;
        }
    }

    // Delivery is numeric-priority based: a lower-numbered vector can preempt a
    // higher-numbered in-flight handler. Exceptions that cannot preempt another
    // exception remain fatal because forward progress is ambiguous.
    if (registers.isInInterrupt()) {
        const uint64_t current_interrupt = registers.getCurrentInterruptNumber();
        if (current_interrupt != Little64Vectors::kNoTrap && current_interrupt <= interrupt_number) {
            if (exception && Little64Vectors::isExceptionVector(current_interrupt)) {
                isRunning = false;
                _recordBootEvent("exception-lockup", interrupt_number, epc, registers.regs[15]);
                _dumpBootEvents("exception could not preempt current handler");
            }
            return false;
        }
    }

    const uint64_t saved_cpu_control = registers.cpu_control;
    const uint64_t saved_interrupt_cpu_control = registers.interrupt_cpu_control;
    const uint64_t saved_trap_cause = registers.trap_cause;
    const uint64_t saved_trap_fault_addr = registers.trap_fault_addr;
    const uint64_t saved_trap_access = registers.trap_access;
    const uint64_t saved_trap_pc = registers.trap_pc;
    const uint64_t saved_trap_aux = registers.trap_aux;

    // Interrupt entry first snapshots cpu_control and forces supervisor mode.
    // This ensures interrupt table fetches are performed with kernel privilege.
    registers.interrupt_cpu_control = saved_cpu_control;
    registers.setUserMode(false);
    registers.setInInterrupt(true);
    registers.setInterruptEnabled(false);
    registers.setCurrentInterruptNumber(interrupt_number);

    uint64_t handler_addr = registers.interrupt_table_base + (interrupt_number * 8);
    const TranslationResult handler_translation = _translateAddress(handler_addr, CpuAccessType::Read);
    if (!handler_translation.valid) {
        if (exception && !isRunning) {
            registers.cpu_control = saved_cpu_control;
            registers.interrupt_cpu_control = saved_interrupt_cpu_control;
            registers.trap_cause = saved_trap_cause;
            registers.trap_fault_addr = saved_trap_fault_addr;
            registers.trap_access = saved_trap_access;
            registers.trap_pc = saved_trap_pc;
            registers.trap_aux = saved_trap_aux;
        }
        isRunning = false;
        _recordBootEvent("exception-lockup", interrupt_number, epc, handler_addr);
        _dumpBootEvents("handler fetch failed");
        return false;
    }
    uint64_t handler = _bus.read64(handler_translation.physical, MemoryAccessType::Read);
    if (handler == 0) {
        registers.cpu_control = saved_cpu_control;
        registers.interrupt_cpu_control = saved_interrupt_cpu_control;
        isRunning = false;
        _recordBootEvent("interrupt-lockup", interrupt_number, epc, handler_addr);
        _dumpBootEvents("interrupt or exception with no handler");
        return false;  // no handler registered
    }

    if (!exception) {
        _setInterruptPending(interrupt_number);
    }

    registers.interrupt_epc = (epc != UINT64_MAX) ? epc : registers.regs[15];  // save return address
    registers.interrupt_eflags = registers.flags;   // save flags
    if (exception) {
        if (registers.trap_cause == Little64Vectors::kNoTrap) {
            registers.trap_cause = interrupt_number;
        }
    }

    // Jump to handler
    registers.regs[15] = handler;
    _recordBootEvent("interrupt-enter", interrupt_number, handler, registers.interrupt_epc);

    return true;
}
