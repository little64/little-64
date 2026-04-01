#include "ram_region.hpp"
#include <cstring>

RamRegion::RamRegion(uint64_t base, uint64_t size, std::string_view name)
    : MemoryRegion(base, size), _data(size, 0), _name(name) {}

RamRegion::RamRegion(uint64_t base, std::vector<uint8_t> init_data, uint64_t total_size, std::string_view name)
    : MemoryRegion(base, total_size), _data(total_size, 0), _name(name) {
    size_t copy_size = std::min(init_data.size(), total_size);
    if (copy_size > 0)
        std::memcpy(_data.data(), init_data.data(), copy_size);
}

uint8_t RamRegion::read8(uint64_t addr) {
    return _data[addr - _base];
}

void RamRegion::write8(uint64_t addr, uint8_t val) {
    _data[addr - _base] = val;
}

uint16_t RamRegion::read16(uint64_t addr) {
    uint16_t val;
    std::memcpy(&val, _data.data() + (addr - _base), sizeof(val));
    return val;
}

void RamRegion::write16(uint64_t addr, uint16_t val) {
    std::memcpy(_data.data() + (addr - _base), &val, sizeof(val));
}

uint32_t RamRegion::read32(uint64_t addr) {
    uint32_t val;
    std::memcpy(&val, _data.data() + (addr - _base), sizeof(val));
    return val;
}

void RamRegion::write32(uint64_t addr, uint32_t val) {
    std::memcpy(_data.data() + (addr - _base), &val, sizeof(val));
}

uint64_t RamRegion::read64(uint64_t addr) {
    uint64_t val;
    std::memcpy(&val, _data.data() + (addr - _base), sizeof(val));
    return val;
}

void RamRegion::write64(uint64_t addr, uint64_t val) {
    std::memcpy(_data.data() + (addr - _base), &val, sizeof(val));
}
