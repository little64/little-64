#include "page_table_builder.hpp"

namespace {

constexpr uint64_t PTE_V = 1ULL << 0;
constexpr uint64_t PTE_R = 1ULL << 1;
constexpr uint64_t PTE_W = 1ULL << 2;
constexpr uint64_t PTE_X = 1ULL << 3;
constexpr uint64_t PTE_G = 1ULL << 5;

void zeroPage(MemoryBus& bus, uint64_t page) {
    for (uint64_t off = 0; off < PageTableBuilder::PAGE_SIZE; off += 8) {
        bus.write64(page + off, 0, MemoryAccessType::Write);
    }
}

uint64_t makeTablePte(uint64_t table_page) {
    return (((table_page >> 12) << 10) | PTE_V);
}

uint64_t makeLeafPte(uint64_t phys_page, bool r, bool w, bool x, bool g) {
    uint64_t pte = ((phys_page >> 12) << 10) | PTE_V;
    if (r) pte |= PTE_R;
    if (w) pte |= PTE_W;
    if (x) pte |= PTE_X;
    if (g) pte |= PTE_G;
    return pte;
}

bool ensureNextLevel(MemoryBus& bus,
                     PageTableBuilder::Allocator& allocator,
                     uint64_t table,
                     uint64_t index,
                     uint64_t& next_table_out) {
    const uint64_t pte_addr = table + index * 8ULL;
    uint64_t pte = bus.read64(pte_addr, MemoryAccessType::Read);
    if ((pte & PTE_V) != 0) {
        next_table_out = ((pte >> 10) << 12);
        return true;
    }

    uint64_t new_page = 0;
    if (!allocator.allocatePage(new_page)) {
        return false;
    }
    zeroPage(bus, new_page);
    bus.write64(pte_addr, makeTablePte(new_page), MemoryAccessType::Write);
    next_table_out = new_page;
    return true;
}

} // namespace

PageTableBuilder::BuildResult PageTableBuilder::createRoot(Allocator& allocator, MemoryBus& bus) {
    uint64_t root = 0;
    if (!allocator.allocatePage(root)) {
        return BuildResult{ .ok = false, .root = 0 };
    }
    zeroPage(bus, root);
    return BuildResult{ .ok = true, .root = root };
}

bool PageTableBuilder::map4K(MemoryBus& bus,
                             Allocator& allocator,
                             uint64_t root,
                             uint64_t virtual_addr,
                             uint64_t physical_addr,
                             bool read,
                             bool write,
                             bool execute,
                             bool global) {
    if (((root | virtual_addr | physical_addr) & (PAGE_SIZE - 1ULL)) != 0) {
        return false;
    }

    const uint64_t idx2 = (virtual_addr >> 30) & 0x1FFULL;
    const uint64_t idx1 = (virtual_addr >> 21) & 0x1FFULL;
    const uint64_t idx0 = (virtual_addr >> 12) & 0x1FFULL;

    uint64_t l1 = 0;
    if (!ensureNextLevel(bus, allocator, root, idx2, l1)) {
        return false;
    }

    uint64_t l0 = 0;
    if (!ensureNextLevel(bus, allocator, l1, idx1, l0)) {
        return false;
    }

    const uint64_t leaf_addr = l0 + idx0 * 8ULL;
    const uint64_t leaf = makeLeafPte(physical_addr, read, write, execute, global);
    bus.write64(leaf_addr, leaf, MemoryAccessType::Write);
    return true;
}
