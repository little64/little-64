#include "emulator_session.hpp"

#include <cstring>

void EmulatorSession::loadProgram(const std::vector<uint16_t>& words, uint64_t base, uint64_t entry_offset) {
    _cpu.loadProgram(words, base, entry_offset);
}

bool EmulatorSession::loadProgramElf(const std::vector<uint8_t>& elf_bytes, uint64_t base) {
    return _cpu.loadProgramElf(elf_bytes, base);
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
    snapshot.interrupt_except = _cpu.registers.interrupt_except;
    std::memcpy(snapshot.interrupt_data, _cpu.registers.interrupt_data, sizeof(snapshot.interrupt_data));
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
