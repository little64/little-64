#pragma once

#include "memory_region.hpp"
#include <vector>

class RomRegion : public MemoryRegion {
public:
    // Data is copied in; size is derived from data.size() (caller must pre-pad to 4K boundary).
    RomRegion(uint64_t base, std::vector<uint8_t> data, std::string_view name = "ROM");

    uint8_t read8(uint64_t addr) override;
    void    write8(uint64_t addr, uint8_t val) override;  // no-op (read-only)

    uint16_t read16(uint64_t addr) override;
    void     write16(uint64_t addr, uint16_t val) override;  // no-op
    uint32_t read32(uint64_t addr) override;
    void     write32(uint64_t addr, uint32_t val) override;  // no-op
    uint64_t read64(uint64_t addr) override;
    void     write64(uint64_t addr, uint64_t val) override;  // no-op
    bool     allows(uint64_t addr, size_t width, MemoryAccessType access) const override;

    std::string_view name() const override { return _name; }

    // Direct buffer access for the GUI memory panel
    const uint8_t* data() const { return _data.data(); }

private:
    std::vector<uint8_t> _data;
    std::string _name;
};
