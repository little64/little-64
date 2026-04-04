#pragma once

#include "memory_bus.hpp"

#include <cstdint>

class PageTableBuilder {
public:
    struct Allocator {
        virtual ~Allocator() = default;
        virtual bool allocatePage(uint64_t& out_physical_page) = 0;
    };

    struct BuildResult {
        bool ok = false;
        uint64_t root = 0;
    };

    static constexpr uint64_t PAGE_SIZE = 4096;

    static BuildResult createRoot(Allocator& allocator, MemoryBus& bus);

    static bool map4K(MemoryBus& bus,
                      Allocator& allocator,
                      uint64_t root,
                      uint64_t virtual_addr,
                      uint64_t physical_addr,
                      bool read,
                      bool write,
                      bool execute,
                      bool global = true);
};
