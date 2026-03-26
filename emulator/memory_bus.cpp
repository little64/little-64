#include "memory_bus.hpp"
#include <stdexcept>
#include <algorithm>

void MemoryBus::addRegion(std::unique_ptr<MemoryRegion> region) {
    uint64_t new_base = region->base();
    uint64_t new_end  = region->end();
    for (const auto& r : _regions) {
        if (new_base < r->end() && new_end > r->base()) {
            throw std::invalid_argument(
                std::string("MemoryBus: region '") + std::string(region->name()) +
                "' overlaps with existing region '" + std::string(r->name()) + "'");
        }
    }
    _regions.push_back(std::move(region));
}

void MemoryBus::removeRegion(std::string_view name) {
    auto it = std::find_if(_regions.begin(), _regions.end(),
        [&](const auto& r) { return r->name() == name; });
    if (it != _regions.end()) _regions.erase(it);
}

void MemoryBus::clearRegions() {
    _regions.clear();
}

MemoryRegion* MemoryBus::findRegion(uint64_t addr) const {
    for (const auto& r : _regions) {
        if (addr >= r->base() && addr < r->end())
            return r.get();
    }
    return nullptr;
}

uint8_t MemoryBus::read8(uint64_t addr) const {
    MemoryRegion* r = findRegion(addr);
    return r ? r->read8(addr) : 0xFF;
}

void MemoryBus::write8(uint64_t addr, uint8_t val) {
    MemoryRegion* r = findRegion(addr);
    if (r) r->write8(addr, val);
}

// For wide accesses: if both ends are in the same region, use the region's optimized
// method. If they straddle a boundary (or either end is unmapped), fall back to bytes.

uint16_t MemoryBus::read16(uint64_t addr) const {
    MemoryRegion* r = findRegion(addr);
    if (r && addr + 1 < r->end()) return r->read16(addr);
    return static_cast<uint16_t>(read8(addr)) |
           (static_cast<uint16_t>(read8(addr + 1)) << 8);
}

void MemoryBus::write16(uint64_t addr, uint16_t val) {
    MemoryRegion* r = findRegion(addr);
    if (r && addr + 1 < r->end()) { r->write16(addr, val); return; }
    write8(addr,     static_cast<uint8_t>(val));
    write8(addr + 1, static_cast<uint8_t>(val >> 8));
}

uint32_t MemoryBus::read32(uint64_t addr) const {
    MemoryRegion* r = findRegion(addr);
    if (r && addr + 3 < r->end()) return r->read32(addr);
    return static_cast<uint32_t>(read16(addr)) |
           (static_cast<uint32_t>(read16(addr + 2)) << 16);
}

void MemoryBus::write32(uint64_t addr, uint32_t val) {
    MemoryRegion* r = findRegion(addr);
    if (r && addr + 3 < r->end()) { r->write32(addr, val); return; }
    write16(addr,     static_cast<uint16_t>(val));
    write16(addr + 2, static_cast<uint16_t>(val >> 16));
}

uint64_t MemoryBus::read64(uint64_t addr) const {
    MemoryRegion* r = findRegion(addr);
    if (r && addr + 7 < r->end()) return r->read64(addr);
    return static_cast<uint64_t>(read32(addr)) |
           (static_cast<uint64_t>(read32(addr + 4)) << 32);
}

void MemoryBus::write64(uint64_t addr, uint64_t val) {
    MemoryRegion* r = findRegion(addr);
    if (r && addr + 7 < r->end()) { r->write64(addr, val); return; }
    write32(addr,     static_cast<uint32_t>(val));
    write32(addr + 4, static_cast<uint32_t>(val >> 32));
}
