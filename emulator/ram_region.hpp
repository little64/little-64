#pragma once

#include "memory_region.hpp"
#include <vector>

class RamRegion : public MemoryRegion {
public:
    RamRegion(uint64_t base, uint64_t size, std::string_view name = "RAM");

    uint8_t read8(uint64_t addr) override;
    void    write8(uint64_t addr, uint8_t val) override;

    uint16_t read16(uint64_t addr) override;
    void     write16(uint64_t addr, uint16_t val) override;
    uint32_t read32(uint64_t addr) override;
    void     write32(uint64_t addr, uint32_t val) override;
    uint64_t read64(uint64_t addr) override;
    void     write64(uint64_t addr, uint64_t val) override;

    std::string_view name() const override { return _name; }

    // Direct buffer access for the GUI memory panel
    const uint8_t* data() const { return _data.data(); }

private:
    std::vector<uint8_t> _data;
    std::string _name;
};
