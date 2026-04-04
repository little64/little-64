#include "emulator_session.hpp"

#include <cstring>

void EmulatorSession::loadProgram(const std::vector<uint16_t>& words, uint64_t base, uint64_t entry_offset) {
    _cpu.loadProgram(words, base, entry_offset);
}

bool EmulatorSession::loadProgramElf(const std::vector<uint8_t>& elf_bytes, uint64_t base) {
    return _cpu.loadProgramElf(elf_bytes, base);
}

bool EmulatorSession::loadProgramElfDirectPaged(const std::vector<uint8_t>& elf_bytes,
                                                uint64_t kernel_physical_base,
                                                uint64_t direct_map_virtual_base) {
    return _cpu.loadProgramElfDirectPaged(elf_bytes, kernel_physical_base, direct_map_virtual_base);
}

void EmulatorSession::cycle() {
    _cpu.cycle();
}

void EmulatorSession::reset() {
    _cpu.reset();
}

void EmulatorSession::assertInterrupt(uint64_t num) {
    _cpu.assertInterrupt(num);
}

bool EmulatorSession::isRunning() const {
    return _cpu.isRunning;
}

uint64_t EmulatorSession::pc() const {
    return _cpu.registers.regs[15];
}

uint64_t EmulatorSession::reg(int index) const {
    return _cpu.registers.regs[index];
}

RegisterSnapshot EmulatorSession::registers() const {
    RegisterSnapshot snapshot{};
    std::memcpy(snapshot.gpr, _cpu.registers.regs, sizeof(snapshot.gpr));
    snapshot.flags = _cpu.registers.flags;
    snapshot.cpu_control = _cpu.registers.cpu_control;
    snapshot.interrupt_table_base = _cpu.registers.interrupt_table_base;
    snapshot.interrupt_mask = _cpu.registers.interrupt_mask;
    snapshot.interrupt_states = _cpu.registers.interrupt_states;
    snapshot.interrupt_epc = _cpu.registers.interrupt_epc;
    snapshot.interrupt_eflags = _cpu.registers.interrupt_eflags;
    snapshot.trap_cause = _cpu.registers.trap_cause;
    snapshot.trap_fault_addr = _cpu.registers.trap_fault_addr;
    snapshot.trap_access = _cpu.registers.trap_access;
    snapshot.trap_pc = _cpu.registers.trap_pc;
    snapshot.trap_aux = _cpu.registers.trap_aux;
    snapshot.page_table_root_physical = _cpu.registers.page_table_root_physical;
    snapshot.boot_info_frame_physical = _cpu.registers.boot_info_frame_physical;
    snapshot.boot_source_page_size = _cpu.registers.boot_source_page_size;
    snapshot.boot_source_page_count = _cpu.registers.boot_source_page_count;
    snapshot.hypercall_caps = _cpu.registers.hypercall_caps;
    return snapshot;
}

uint8_t EmulatorSession::memoryRead8(uint64_t addr) const {
    return _cpu.getMemoryBus().read8(addr);
}

std::vector<MemoryRegionView> EmulatorSession::memoryRegions() const {
    std::vector<MemoryRegionView> out;
    const auto& regions = _cpu.getMemoryBus().regions();
    out.reserve(regions.size());
    for (const auto& region : regions) {
        out.push_back(MemoryRegionView{
            .base = region->base(),
            .size = region->size(),
            .name = std::string(region->name()),
        });
    }
    return out;
}

std::string EmulatorSession::drainSerialTx() {
    SerialDevice* serial = _cpu.getSerial();
    if (!serial) {
        return {};
    }

    std::string output = serial->txBuffer();
    if (!output.empty()) {
        serial->clearTxBuffer();
    }
    return output;
}
