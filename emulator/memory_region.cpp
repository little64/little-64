#include "memory_region.hpp"

uint16_t MemoryRegion::read16(uint64_t addr) {
    return static_cast<uint16_t>(read8(addr)) |
           (static_cast<uint16_t>(read8(addr + 1)) << 8);
}

void MemoryRegion::write16(uint64_t addr, uint16_t val) {
    write8(addr,     static_cast<uint8_t>(val));
    write8(addr + 1, static_cast<uint8_t>(val >> 8));
}

uint32_t MemoryRegion::read32(uint64_t addr) {
    return static_cast<uint32_t>(read16(addr)) |
           (static_cast<uint32_t>(read16(addr + 2)) << 16);
}

void MemoryRegion::write32(uint64_t addr, uint32_t val) {
    write16(addr,     static_cast<uint16_t>(val));
    write16(addr + 2, static_cast<uint16_t>(val >> 16));
}

uint64_t MemoryRegion::read64(uint64_t addr) {
    return static_cast<uint64_t>(read32(addr)) |
           (static_cast<uint64_t>(read32(addr + 4)) << 32);
}

void MemoryRegion::write64(uint64_t addr, uint64_t val) {
    write32(addr,     static_cast<uint32_t>(val));
    write32(addr + 4, static_cast<uint32_t>(val >> 32));
}
