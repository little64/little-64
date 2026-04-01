#pragma once

#include "memory_region.hpp"

class Device : public MemoryRegion {
public:
    Device(uint64_t base, uint64_t size) : MemoryRegion(base, size) {}
    ~Device() override = default;

    virtual void reset() {}
    virtual void tick() {}
};
