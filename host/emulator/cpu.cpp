#include "cpu.hpp"
#include "machine_config.hpp"
#include "opcodes.hpp"
#include "page_table_builder.hpp"
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

} // namespace

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
            if (registers.isUserMode()) {
                registers.trap_pc = registers.regs[15] - 2;
                registers.trap_cause = AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION;
                _raiseInterrupt(AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION, true, registers.regs[15] - 2);
                return;
            }
            // Load special register, e.g. for CPU control and interrupt table base
            registers.regs[instr.rd] = registers.getSpecialRegister(b);
            break;
        }

        case GP::Opcode::SSR: {
            if (registers.isUserMode()) {
                registers.trap_pc = registers.regs[15] - 2;
                registers.trap_cause = AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION;
                _raiseInterrupt(AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION, true, registers.regs[15] - 2);
                return;
            }
            // Store special register
            registers.setSpecialRegister(b, a);
            if (b == 15) {
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
            break;
        }

        case GP::Opcode::STOP: {
            if (registers.isUserMode()) {
                registers.trap_pc = registers.regs[15] - 2;
                registers.trap_cause = AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION;
                _raiseInterrupt(AddressTranslator::TRAP_PRIVILEGED_INSTRUCTION, true, registers.regs[15] - 2);
                return;
            }
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
    registers.trap_aux = result.trap_aux;

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
            registers.regs[4] = 0xFFFFFFFFFFFF0000ULL;
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
}

bool Little64CPU::loadProgramElfDirectPaged(const std::vector<uint8_t>& elf_bytes,
                                            uint64_t kernel_physical_base,
                                            uint64_t direct_map_virtual_base) {
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

    constexpr uint64_t RAM_EXTRA = 64 * 1024 * 1024;
    constexpr uint64_t SERIAL_BASE = 0xFFFFFFFFFFFF0000ULL;
    const uint64_t total_ram = image_span + RAM_EXTRA;

    MachineConfig cfg;
    cfg.addPreloadedRam(kernel_physical_base, std::move(ram_bytes), total_ram, "MEM")
        .addSerial(SERIAL_BASE, "SERIAL");
    cfg.applyTo(_bus, _devices, this);

    _mem_base = kernel_physical_base;
    _mem_size = total_ram;
    _page_table_alloc_cursor = _mem_base + _mem_size;

    registers = {};
    registers.boot_source_page_size = 4096;
    registers.boot_source_page_count = (_boot_source_bytes.size() + 4095ULL) / 4096ULL;
    registers.hypercall_caps = HYPERCALL_CAP_MINIMAL_BOOT;

    CpuPageAllocator allocator(*this);
    const auto root = PageTableBuilder::createRoot(allocator, _bus);
    if (!root.ok) {
        return false;
    }

    // Temporary identity mapping for initial low memory transition.
    const uint64_t identity_limit = std::min<uint64_t>(_mem_base + 2 * 1024 * 1024, _mem_base + _mem_size);
    for (uint64_t pa = _mem_base; pa < identity_limit; pa += PAGE) {
        if (!PageTableBuilder::map4K(_bus, allocator, root.root, pa, pa, true, true, true, true)) {
            return false;
        }
    }

    // Direct-map full RAM in higher half.
    for (uint64_t off = 0; off < _mem_size; off += PAGE) {
        const uint64_t pa = _mem_base + off;
        const uint64_t va = direct_map_virtual_base + off;
        if (!PageTableBuilder::map4K(_bus, allocator, root.root, va, pa, true, true, true, true)) {
            return false;
        }
    }

    // Segment-accurate mappings for kernel virtual addresses.
    for (uint16_t i = 0; i < ehdr->e_phnum; ++i) {
        const Elf64_Phdr* ph = reinterpret_cast<const Elf64_Phdr*>(
            elf_bytes.data() + ehdr->e_phoff + static_cast<uint64_t>(i) * ehdr->e_phentsize);
        if (ph->p_type != PT_LOAD) continue;

        const uint64_t seg_start = (ph->p_vaddr / PAGE) * PAGE;
        const uint64_t seg_end = ((ph->p_vaddr + ph->p_memsz + PAGE - 1) / PAGE) * PAGE;
        const bool r = (ph->p_flags & PF_R) != 0;
        const bool w = (ph->p_flags & PF_W) != 0;
        const bool x = (ph->p_flags & PF_X) != 0;

        for (uint64_t va = seg_start; va < seg_end; va += PAGE) {
            const uint64_t pa = kernel_physical_base + (va - virt_base);
            if (!PageTableBuilder::map4K(_bus, allocator, root.root, va, pa, r, w, x, true)) {
                return false;
            }
        }
    }

    registers.page_table_root_physical = root.root;
    registers.setPagingEnabled(true);
    registers.regs[13] = direct_map_virtual_base + (_mem_size - 8);
    registers.regs[15] = ehdr->e_entry;
    isRunning = true;
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

    // Save full CPU control state (including privilege level) and force supervisor mode on interrupt entry
    registers.interrupt_cpu_control = registers.cpu_control;
    registers.setUserMode(false);

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
