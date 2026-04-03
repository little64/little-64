#include "rom_region.hpp"
#include <cstring>

RomRegion::RomRegion(uint64_t base, std::vector<uint8_t> data, std::string_view name)
    : MemoryRegion(base, data.size()), _data(std::move(data)), _name(name) {}

uint8_t RomRegion::read8(uint64_t addr) {
    return _data[addr - _base];
}

void RomRegion::write8(uint64_t /*addr*/, uint8_t /*val*/) {
    // Read-only; writes silently ignored
}

uint16_t RomRegion::read16(uint64_t addr) {
    uint16_t val;
    std::memcpy(&val, _data.data() + (addr - _base), sizeof(val));
    return val;
}

void RomRegion::write16(uint64_t /*addr*/, uint16_t /*val*/) {}

uint32_t RomRegion::read32(uint64_t addr) {
    uint32_t val;
    std::memcpy(&val, _data.data() + (addr - _base), sizeof(val));
    return val;
}

void RomRegion::write32(uint64_t /*addr*/, uint32_t /*val*/) {}

uint64_t RomRegion::read64(uint64_t addr) {
    uint64_t val;
    std::memcpy(&val, _data.data() + (addr - _base), sizeof(val));
    return val;
}

void RomRegion::write64(uint64_t /*addr*/, uint64_t /*val*/) {}

bool RomRegion::allows(uint64_t addr, size_t width, MemoryAccessType access) const {
    if (!MemoryRegion::allows(addr, width, access)) {
        return false;
    }
    return access != MemoryAccessType::Write;
}
