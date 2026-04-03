#pragma once

#include "memory_region.hpp"
#include <memory>
#include <string_view>
#include <vector>

class MemoryBus {
public:
    MemoryBus() = default;

    // Adds a region. Throws std::invalid_argument if it overlaps an existing region.
    void addRegion(std::unique_ptr<MemoryRegion> region);

    // Removes a region by name. No-op if name not found.
    void removeRegion(std::string_view name);

    // Removes all regions.
    void clearRegions();

    const std::vector<std::unique_ptr<MemoryRegion>>& regions() const { return _regions; }

    // Read/write interface. Unmapped reads return 0xFF; unmapped writes are no-ops.
    uint8_t  read8 (uint64_t addr, MemoryAccessType access = MemoryAccessType::Read) const;
    void     write8(uint64_t addr, uint8_t val, MemoryAccessType access = MemoryAccessType::Write);
    uint16_t read16(uint64_t addr, MemoryAccessType access = MemoryAccessType::Read) const;
    void     write16(uint64_t addr, uint16_t val, MemoryAccessType access = MemoryAccessType::Write);
    uint32_t read32(uint64_t addr, MemoryAccessType access = MemoryAccessType::Read) const;
    void     write32(uint64_t addr, uint32_t val, MemoryAccessType access = MemoryAccessType::Write);
    uint64_t read64(uint64_t addr, MemoryAccessType access = MemoryAccessType::Read) const;
    void     write64(uint64_t addr, uint64_t val, MemoryAccessType access = MemoryAccessType::Write);

private:
    MemoryRegion* findRegion(uint64_t addr) const;
    MemoryRegion* resolveAccessRange(uint64_t addr, uint64_t width, MemoryAccessType access) const;
    bool spansSingleRegion(uint64_t addr, uint64_t width, MemoryAccessType access) const;

    std::vector<std::unique_ptr<MemoryRegion>> _regions;
};
