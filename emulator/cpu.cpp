#include "cpu.hpp"
#include "opcodes.hpp"
#include "ram_region.hpp"
#include "rom_region.hpp"
#include <memory>

Little64CPU::Little64CPU() {
}

void Little64CPU::cycle() {
    if (!isRunning)
        return;

    // R0 is always zero
    registers.regs[0] = 0;

    uint64_t pc = registers.regs[15];
    uint16_t instr_word = _bus.read16(pc);
    Instruction instr(instr_word);

    registers.regs[15] += 2;  // advance PC before dispatch (so pc_rel is relative to next instruction)

    dispatchInstruction(instr);

    registers.regs[0] = 0;  // enforce R0=0 after any write

    // Poll for pending interrupts each cycle
    uint64_t pending = registers.interrupt_states & registers.interrupt_mask;
    if (pending) {
        for (int i = 0; i < 64; ++i) {
            if (pending & (1ULL << i)) {
                _raiseInterrupt(i);
                break;
            }
        }
    }
}

void Little64CPU::dispatchInstruction(const Instruction& instr) {
    switch (instr.format) {
        case 0: _dispatchLSReg(instr);   break;
        case 1: _dispatchLSPCRel(instr); break;
        case 2: _dispatchLDI(instr);     break;
        case 3: _dispatchGP(instr);      break;
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
    uint64_t addr = registers.regs[instr.rs1] + (instr.offset2 * 2);

    switch (static_cast<LS::Opcode>(instr.opcode_ls)) {
        case LS::Opcode::LOAD:
            registers.regs[instr.rd] = _readMemory64(addr);
            break;
        case LS::Opcode::STORE:
            _writeMemory64(addr, registers.regs[instr.rd]);
            break;
        case LS::Opcode::PUSH:
            registers.regs[instr.rd] -= 8;
            _writeMemory64(registers.regs[instr.rd], registers.regs[instr.rs1]);
            break;
        case LS::Opcode::POP:
            registers.regs[instr.rs1] = _readMemory64(registers.regs[instr.rd]);
            registers.regs[instr.rd] += 8;
            break;
        case LS::Opcode::MOVE:
            registers.regs[instr.rd] = addr;
            break;
        case LS::Opcode::BYTE_LOAD:
            registers.regs[instr.rd] = _readMemory8(addr);
            break;
        case LS::Opcode::BYTE_STORE:
            _writeMemory8(addr, registers.regs[instr.rd] & 0xFF);
            break;
        case LS::Opcode::SHORT_LOAD:
            registers.regs[instr.rd] = _readMemory16(addr);
            break;
        case LS::Opcode::SHORT_STORE:
            _writeMemory16(addr, registers.regs[instr.rd] & 0xFFFF);
            break;
        case LS::Opcode::WORD_LOAD:
            registers.regs[instr.rd] = _readMemory32(addr);
            break;
        case LS::Opcode::WORD_STORE:
            _writeMemory32(addr, registers.regs[instr.rd] & 0xFFFFFFFF);
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
}

void Little64CPU::_dispatchLSPCRel(const Instruction& instr) {
    // PC is already post-incremented; pc_rel is in instruction units (×2 bytes)
    uint64_t effective = registers.regs[15] + (static_cast<int64_t>(instr.pc_rel) * 2);

    switch (static_cast<LS::Opcode>(instr.opcode_ls)) {
        case LS::Opcode::LOAD:
            registers.regs[instr.rd] = _readMemory64(effective);
            break;
        case LS::Opcode::STORE:
            _writeMemory64(effective, registers.regs[instr.rd]);
            break;
        case LS::Opcode::PUSH: {
            uint64_t value = _readMemory64(effective);
            registers.regs[instr.rd] -= 8;
            _writeMemory64(registers.regs[instr.rd], value);
            break;
        }
        case LS::Opcode::POP: {
            uint64_t value = _readMemory64(registers.regs[instr.rd]);
            registers.regs[instr.rd] += 8;
            _writeMemory64(effective, value);
            break;
        }
        case LS::Opcode::MOVE:
            registers.regs[instr.rd] = effective;
            break;
        case LS::Opcode::BYTE_LOAD:
            registers.regs[instr.rd] = _readMemory8(effective);
            break;
        case LS::Opcode::BYTE_STORE:
            _writeMemory8(effective, registers.regs[instr.rd] & 0xFF);
            break;
        case LS::Opcode::SHORT_LOAD:
            registers.regs[instr.rd] = _readMemory16(effective);
            break;
        case LS::Opcode::SHORT_STORE:
            _writeMemory16(effective, registers.regs[instr.rd] & 0xFFFF);
            break;
        case LS::Opcode::WORD_LOAD:
            registers.regs[instr.rd] = _readMemory32(effective);
            break;
        case LS::Opcode::WORD_STORE:
            _writeMemory32(effective, registers.regs[instr.rd] & 0xFFFFFFFF);
            break;
        case LS::Opcode::JUMP_Z:
        case LS::Opcode::JUMP_C:
        case LS::Opcode::JUMP_S:
        case LS::Opcode::JUMP_GT:
        case LS::Opcode::JUMP_LT:
            if (checkCondition(registers.flags, static_cast<LS::Opcode>(instr.opcode_ls)))
                registers.regs[instr.rd] = effective;
            break;
    }
}

void Little64CPU::_dispatchLDI(const Instruction& instr) {
    if (instr.shift == 0) {
        registers.regs[instr.rd] = instr.imm8;
    } else {
        registers.regs[instr.rd] |= (static_cast<uint64_t>(instr.imm8) << (instr.shift * 8));

        // If the shift is the max value (3), also sign-extend the immediate to fill the upper bits of the register.
        if (instr.shift == 3 && (instr.imm8 & 0x80) != 0) {
            registers.regs[instr.rd] |= 0xFFFFFFFFFFFFFF00ULL;
        }
    }
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

        case GP::Opcode::LSR: {
            // Load special register, e.g. for CPU control and interrupt table base
            registers.regs[instr.rd] = registers.getSpecialRegister(b);
            break;
        }

        case GP::Opcode::SSR: {
            // Store special register
            registers.setSpecialRegister(b, a);
            break;
        }

        case GP::Opcode::IRET: {
            registers.regs[15] = registers.interrupt_epc;
            registers.flags    = registers.interrupt_eflags;
            registers.setInInterrupt(false);
            registers.setInterruptEnabled(true);
            registers.setCurrentInterruptNumber(0);
            break;
        }

        case GP::Opcode::STOP: {
            isRunning = false;
            break;
        }
    }
}

void Little64CPU::loadProgram(const std::vector<uint16_t>& words, uint64_t base) {
    // Convert 16-bit words to bytes (little-endian)
    std::vector<uint8_t> bytes;
    bytes.reserve(words.size() * 2);
    for (uint16_t w : words) {
        bytes.push_back(w & 0xFF);
        bytes.push_back((w >> 8) & 0xFF);
    }

    // Align ROM size up to 4K boundary
    constexpr uint64_t PAGE = 4096;
    uint64_t rom_size = (bytes.size() + PAGE - 1) / PAGE * PAGE;
    if (rom_size == 0) rom_size = PAGE;
    bytes.resize(rom_size, 0);

    constexpr uint64_t RAM_SIZE = 64 * 1024 * 1024;  // 64MB
    constexpr uint64_t SERIAL_BASE = 0xFFFFFFFFFFFF0000ULL;

    _bus.clearRegions();
    _bus.addRegion(std::make_unique<RomRegion>(base, std::move(bytes), "ROM"));
    _bus.addRegion(std::make_unique<RamRegion>(base + rom_size, RAM_SIZE, "RAM"));
    _bus.addRegion(std::make_unique<SerialDevice>(SERIAL_BASE, "SERIAL"));

    // Reset CPU state
    registers = {};
    registers.regs[15] = base;
    isRunning = true;
}

SerialDevice* Little64CPU::getSerial() {
    for (auto& r : _bus.regions()) {
        if (auto* s = dynamic_cast<SerialDevice*>(r.get()))
            return s;
    }
    return nullptr;
}

bool Little64CPU::_raiseInterrupt(uint64_t interrupt_number, bool exception, uint64_t epc) {
    if(!registers.isInterruptEnabled()) {
        // interrupts disabled; interrupts are ignored, but exceptions cause lockup
        if (exception)
            isRunning = false;
        return false;
    }

    // Non-exception interrupts must have their mask bit set
    if (!exception && !(registers.interrupt_mask & (1ULL << interrupt_number)))
        return false;

    // Check if we are currently in an interrupt.
    // Only a strictly higher-priority (lower-numbered) exception can preempt.
    // Regular interrupts cannot preempt at all; same-number exceptions are also blocked.
    if(registers.isInInterrupt() && ((registers.getCurrentInterruptNumber() <= interrupt_number) || !exception)) {
        // Already in an interrupt
        // The CPU will automatically check each cycle if it can re-raise this interrupt as long as it remains asserted
        return false;
    }

    uint64_t handler_addr = registers.interrupt_table_base + (interrupt_number * 8);
    uint64_t handler = _bus.read64(handler_addr);
    if (handler == 0)
        return false;  // no handler registered

    // Set interrupt state and disable further interrupts
    registers.interrupt_states |= (1ULL << (interrupt_number));
    registers.setInInterrupt(true);
    registers.setInterruptEnabled(false);

    // Set the currently handled interrupt number in cpu_control, to avoid re-raising the same interrupt while we're still handling it
    registers.setCurrentInterruptNumber(interrupt_number);

    registers.interrupt_epc = (epc != UINT64_MAX) ? epc : registers.regs[15];  // save return address
    registers.interrupt_eflags = registers.flags;   // save flags
    if (exception) {
        // For exceptions, also write the exception number to "interrupt_except" for the handler to inspect
        // TODO: a better format for this, maybe multiple registers when paging is implemented?
        registers.interrupt_except = interrupt_number;
    }

    // Jump to handler
    registers.regs[15] = handler;

    return true;
}
