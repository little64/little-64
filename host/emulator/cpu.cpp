#include "cpu.hpp"
#include "machine_config.hpp"
#include "opcodes.hpp"
#include "ram_region.hpp"
#include <memory>
#include <algorithm>
#include <cstring>
#include <iostream>
#include <elf.h>

#ifndef EM_LITTLE64
#define EM_LITTLE64 0x4C36
#endif

Little64CPU::Little64CPU() {
}

void Little64CPU::reset() {
    registers = {};
    isRunning = true;
    for (Device* device : _devices) {
        if (device) {
            device->reset();
        }
    }
}

void Little64CPU::cycle() {
    if (!isRunning)
        return;

    // R0 is always zero
    registers.regs[0] = 0;

    uint64_t pc = registers.regs[15];
    uint16_t instr_word = _readMemory16(pc, pc, CpuAccessType::Execute);
    if (!isRunning) {
        return;
    }
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

    for (Device* device : _devices) {
        if (device) {
            device->tick();
        }
    }
}

void Little64CPU::assertInterrupt(uint64_t num) {
    if (num < 64) {
        registers.interrupt_states |= (1ULL << num);
    }
}

void Little64CPU::clearInterrupt(uint64_t num) {
    if (num < 64) {
        registers.interrupt_states &= ~(1ULL << num);
    }
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

    switch (static_cast<LS::Opcode>(instr.opcode_ls)) {
        case LS::Opcode::LOAD:
            registers.regs[instr.rd] = _readMemory64(addr, op_pc);
            break;
        case LS::Opcode::STORE:
            _writeMemory64(addr, registers.regs[instr.rd], op_pc);
            break;
        case LS::Opcode::PUSH:
            registers.regs[instr.rd] -= 8;
            _writeMemory64(registers.regs[instr.rd], registers.regs[instr.rs1], op_pc);
            break;
        case LS::Opcode::POP:
            registers.regs[instr.rs1] = _readMemory64(registers.regs[instr.rd], op_pc);
            registers.regs[instr.rd] += 8;
            break;
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
}

void Little64CPU::_dispatchLSPCRel(const Instruction& instr) {
    const uint64_t op_pc = registers.regs[15] - 2;
    // PC is already post-incremented; pc_rel is in instruction units (×2 bytes)
    uint64_t effective = registers.regs[15] + (static_cast<int64_t>(instr.pc_rel) * 2);

    switch (static_cast<LS::Opcode>(instr.opcode_ls)) {
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
            break;
        }
        case LS::Opcode::POP: {
            uint64_t value = _readMemory64(registers.regs[instr.rd], op_pc);
            registers.regs[instr.rd] += 8;
            _writeMemory64(effective, value, op_pc);
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
            std::cerr << "STOP instruction hit. Register state:" << std::endl;
            for (int i = 0; i < 16; ++i) {
                std::cerr << "  R" << i << ": 0x" << std::hex << registers.regs[i] << std::dec << std::endl;
            }
            isRunning = false;
            break;
        }
    }
}

Little64CPU::TranslationResult Little64CPU::_translateAddress(uint64_t virtual_addr, CpuAccessType access) const {
    if (access == CpuAccessType::Execute && (virtual_addr & 0x1ULL)) {
        return TranslationResult{
            .valid = false,
            .physical = 0,
            .trap_cause = 62,
        };
    }

    return TranslationResult{
        .valid = true,
        .physical = virtual_addr,
        .trap_cause = 0,
    };
}

bool Little64CPU::_mapAddress(uint64_t virtual_addr, CpuAccessType access, uint64_t operation_pc, uint64_t& physical_out) {
    const TranslationResult result = _translateAddress(virtual_addr, access);
    if (result.valid) {
        physical_out = result.physical;
        return true;
    }

    registers.trap_cause = result.trap_cause;
    registers.trap_fault_addr = virtual_addr;
    registers.trap_access = static_cast<uint64_t>(access);
    registers.trap_pc = operation_pc;
    registers.trap_aux = 0;

    _raiseInterrupt(result.trap_cause, true, operation_pc);
    return false;
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
    _bus.write8(physical, v, MemoryAccessType::Write);
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
    _bus.write16(physical, v, MemoryAccessType::Write);
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
    _bus.write32(physical, v, MemoryAccessType::Write);
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
    _bus.write64(physical, v, MemoryAccessType::Write);
}

bool Little64CPU::loadProgramElf(const std::vector<uint8_t>& elf_bytes, uint64_t /*base_unused*/) {
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
    constexpr uint64_t SERIAL_BASE = 0xFFFFFFFFFFFF0000ULL;
    uint64_t total_ram = alloc_size + RAM_EXTRA;

     MachineConfig cfg;
     cfg.addPreloadedRam(base_addr, std::move(ram_bytes), total_ram, "MEM")
         .addSerial(SERIAL_BASE, "SERIAL");
     cfg.applyTo(_bus, _devices, this);

    registers = {};
    registers.regs[13] = base_addr + total_ram - 8;
    registers.regs[15] = ehdr->e_entry;
    isRunning = true;

    return true;
}

void Little64CPU::loadProgram(const std::vector<uint16_t>& words, uint64_t base, uint64_t entry_offset) {
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
    constexpr uint64_t SERIAL_BASE = 0xFFFFFFFFFFFF0000ULL;
    uint64_t total_size = prog_size + RAM_SIZE;

     MachineConfig cfg;
     cfg.addPreloadedRam(base, std::move(bytes), total_size, "MEM")
         .addSerial(SERIAL_BASE, "SERIAL");
     cfg.applyTo(_bus, _devices, this);

    // Reset CPU state.
    registers = {};
    // R13 is the stack pointer.  Initialise it to the top of the memory region
    // (stacks grow downward) so that C/C++ function prologues work correctly.
    registers.regs[13] = base + total_size - 8;
    registers.regs[15] = base + entry_offset;
    isRunning = true;
}

SerialDevice* Little64CPU::getSerial() {
    for (Device* d : _devices) {
        if (auto* s = dynamic_cast<SerialDevice*>(d))
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
    uint64_t handler = _readMemory64(handler_addr, registers.regs[15]);
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
        if (registers.trap_cause == 0) {
            registers.trap_cause = interrupt_number;
        }
    }

    // Jump to handler
    registers.regs[15] = handler;

    return true;
}
