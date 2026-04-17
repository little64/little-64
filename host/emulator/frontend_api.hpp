#pragma once

#include <cstdint>

#include "special_register_layout.hpp"
#include <string>
#include <vector>

struct MemoryRegionView {
    uint64_t base;
    uint64_t size;
    std::string name;
};

struct RegisterSnapshot {
    static constexpr uint64_t kSpecialRegisterCount = Little64SpecialRegisters::kVisibleDebugRegisterCount;

    uint64_t gpr[16]{};
    uint64_t flags = 0;

    uint64_t cpu_control = 0;
    uint64_t thread_pointer = 0;
    uint64_t interrupt_table_base = 0;
    uint64_t interrupt_mask = 0;
    uint64_t interrupt_states = 0;
    uint64_t interrupt_epc = 0;
    uint64_t interrupt_eflags = 0;
    uint64_t interrupt_cpu_control = 0;
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
    uint64_t interrupt_mask_high = 0;
    uint64_t interrupt_states_high = 0;

    constexpr uint64_t getSpecialRegisterBySelector(uint64_t selector) const {
        switch (Little64SpecialRegisters::normalizeSelector(selector)) {
            case Little64SpecialRegisters::kCpuControl: return cpu_control;
            case Little64SpecialRegisters::kUserThreadPointer: return thread_pointer;
            case Little64SpecialRegisters::kPageTableRootPhysical: return page_table_root_physical;
            case Little64SpecialRegisters::kBootInfoFramePhysical: return boot_info_frame_physical;
            case Little64SpecialRegisters::kBootSourcePageSize: return boot_source_page_size;
            case Little64SpecialRegisters::kBootSourcePageCount: return boot_source_page_count;
            case Little64SpecialRegisters::kHypercallCaps: return hypercall_caps;
            case Little64SpecialRegisters::kInterruptTableBase: return interrupt_table_base;
            case Little64SpecialRegisters::kInterruptMask: return interrupt_mask;
            case Little64SpecialRegisters::kInterruptMaskHigh: return interrupt_mask_high;
            case Little64SpecialRegisters::kInterruptStates: return interrupt_states;
            case Little64SpecialRegisters::kInterruptStatesHigh: return interrupt_states_high;
            case Little64SpecialRegisters::kInterruptEpc: return interrupt_epc;
            case Little64SpecialRegisters::kInterruptEflags: return interrupt_eflags;
            case Little64SpecialRegisters::kInterruptCpuControl: return interrupt_cpu_control;
            case Little64SpecialRegisters::kTrapCause: return trap_cause;
            case Little64SpecialRegisters::kTrapFaultAddr: return trap_fault_addr;
            case Little64SpecialRegisters::kTrapAccess: return trap_access;
            case Little64SpecialRegisters::kTrapPc: return trap_pc;
            case Little64SpecialRegisters::kTrapAux: return trap_aux;
            default: return 0;
        }
    }

    constexpr uint64_t getSpecialRegisterByID(uint64_t ordinal) const {
        return getSpecialRegisterBySelector(Little64SpecialRegisters::selectorForDebugOrdinal(ordinal));
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
    virtual bool loadProgramLiteXBootRomImage(const std::vector<uint8_t>& bootrom_bytes) = 0;
    virtual bool loadProgramLiteXFlashImage(const std::vector<uint8_t>& flash_bytes) = 0;
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
