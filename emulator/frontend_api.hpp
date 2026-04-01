#pragma once

#include <cstdint>
#include <string>
#include <vector>

struct MemoryRegionView {
    uint64_t base;
    uint64_t size;
    std::string name;
};

struct RegisterSnapshot {
    uint64_t gpr[16]{};
    uint64_t flags = 0;

    uint64_t cpu_control = 0;
    uint64_t interrupt_table_base = 0;
    uint64_t interrupt_mask = 0;
    uint64_t interrupt_states = 0;
    uint64_t interrupt_epc = 0;
    uint64_t interrupt_eflags = 0;
    uint64_t interrupt_except = 0;
    uint64_t interrupt_data[4]{};
};

class IEmulatorRuntime {
public:
    virtual ~IEmulatorRuntime() = default;

    virtual void loadProgram(const std::vector<uint16_t>& words, uint64_t base = 0, uint64_t entry_offset = 0) = 0;
    virtual bool loadProgramElf(const std::vector<uint8_t>& elf_bytes, uint64_t base = 0) = 0;
    virtual void cycle() = 0;
    virtual void reset() = 0;
    virtual void assertInterrupt(uint64_t num) = 0;

    virtual bool isRunning() const = 0;
    virtual uint64_t pc() const = 0;
    virtual uint64_t reg(int index) const = 0;
    virtual RegisterSnapshot registers() const = 0;

    virtual uint8_t memoryRead8(uint64_t addr) const = 0;
    virtual std::vector<MemoryRegionView> memoryRegions() const = 0;

    virtual std::string drainSerialTx() = 0;
};
