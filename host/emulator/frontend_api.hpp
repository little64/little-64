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
    uint64_t trap_cause = 0;
    uint64_t trap_fault_addr = 0;
    uint64_t trap_access = 0;
    uint64_t trap_pc = 0;
    uint64_t trap_aux = 0;
    uint64_t page_table_root_physical = 0;
    uint64_t boot_info_frame_physical = 0;
    uint64_t boot_source_page_size = 0;
    uint64_t boot_source_page_count = 0;
    uint64_t hypercall_caps = 0;

    constexpr uint64_t getSpecialRegisterByID(uint64_t id) const {
        switch(id) {
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
            default: return 0;
        }
    }
};

class IEmulatorRuntime {
public:
    virtual ~IEmulatorRuntime() = default;

    virtual void loadProgram(const std::vector<uint16_t>& words, uint64_t base = 0, uint64_t entry_offset = 0) = 0;
    virtual bool loadProgramElf(const std::vector<uint8_t>& elf_bytes, uint64_t base = 0) = 0;
    virtual bool loadProgramElfDirectPaged(const std::vector<uint8_t>& elf_bytes,
                                           uint64_t kernel_physical_base = 0x100000,
                                           uint64_t direct_map_virtual_base = 0xFFFFFFC000000000ULL) = 0;
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
