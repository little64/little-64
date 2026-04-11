#include "address_translator.hpp"

namespace {

constexpr uint64_t PTE_V = 1ULL << 0;
constexpr uint64_t PTE_R = 1ULL << 1;
constexpr uint64_t PTE_W = 1ULL << 2;
constexpr uint64_t PTE_X = 1ULL << 3;
constexpr uint64_t PTE_U = 1ULL << 4;
constexpr uint64_t PTE_A = 1ULL << 6;
constexpr uint64_t PTE_D = 1ULL << 7;

constexpr uint64_t PTE_RESERVED_MASK = 0xFFC0000000000000ULL; // bits [63:54], validated for non-leaf tables

} // namespace

bool AddressTranslator::_isCanonical39(uint64_t addr) {
    const uint64_t sign_bit = (addr >> 38) & 1ULL;
    const uint64_t upper = addr >> 39;
    if (sign_bit == 0) {
        return upper == 0;
    }
    return upper == ((1ULL << 25) - 1ULL);
}

uint64_t AddressTranslator::_encodeAux(uint64_t subtype, uint64_t level) {
    return (subtype & 0xFULL) | ((level & 0xFFULL) << 8);
}

PagingTranslateResult AddressTranslator::translate(const MemoryBus& bus,
                                                  const PagingConfig& config,
                                                  uint64_t virtual_addr,
                                                  PagingAccessType access) const {
    auto makeFault = [&](uint64_t cause, uint64_t subtype, uint64_t level) {
        return PagingTranslateResult{
            .valid = false,
            .physical = 0,
            .trap_cause = cause,
            .trap_aux = _encodeAux(subtype, level),
        };
    };

    auto permissionAllowed = [&](uint64_t pte) {
        switch (access) {
            case PagingAccessType::Read:
                return (pte & PTE_R) != 0;
            case PagingAccessType::Write:
                return (pte & PTE_W) != 0;
            case PagingAccessType::Execute:
                return (pte & PTE_X) != 0;
        }
        return false;
    };

    auto resolveLeaf = [&](uint64_t leaf, uint64_t level, uint64_t page_shift) -> PagingTranslateResult {
        if ((leaf & (PTE_R | PTE_W | PTE_X)) == 0)
            return makeFault(TRAP_PAGE_FAULT_NOT_PRESENT, AUX_SUBTYPE_NO_VALID_PTE, level);

        if (!permissionAllowed(leaf))
            return makeFault(TRAP_PAGE_FAULT_PERMISSION, AUX_SUBTYPE_PERMISSION, level);

        if (config.is_user && !(leaf & PTE_U))
            return makeFault(TRAP_PAGE_FAULT_PERMISSION, AUX_SUBTYPE_PERMISSION, level);

        const uint64_t page_size = 1ULL << page_shift;
        const uint64_t page_mask = page_size - 1ULL;
        const uint64_t page_base = ((leaf >> 10) << 12);

        return PagingTranslateResult{
            .valid = true,
            .physical = page_base + (virtual_addr & page_mask),
            .trap_cause = 0,
            .trap_aux = 0,
        };
    };

    if (access == PagingAccessType::Execute && (virtual_addr & 0x1ULL)) {
        return makeFault(TRAP_EXEC_ALIGN, AUX_SUBTYPE_NONE, 0);
    }

    if (!config.enabled) {
        return PagingTranslateResult{
            .valid = true,
            .physical = virtual_addr,
            .trap_cause = 0,
            .trap_aux = 0,
        };
    }

    if ((config.root_table_physical & (PAGE_SIZE - 1ULL)) != 0) {
        return makeFault(TRAP_PAGE_FAULT_RESERVED, AUX_SUBTYPE_RESERVED_BIT, 2);
    }

    if (!_isCanonical39(virtual_addr)) {
        return makeFault(TRAP_PAGE_FAULT_CANONICAL, AUX_SUBTYPE_CANONICAL, 2);
    }

    const uint64_t idx2 = (virtual_addr >> 30) & 0x1FFULL;
    const uint64_t idx1 = (virtual_addr >> 21) & 0x1FFULL;
    const uint64_t idx0 = (virtual_addr >> 12) & 0x1FFULL;

    uint64_t table = config.root_table_physical;
    const uint64_t indices[3] = { idx2, idx1, idx0 };

    for (uint64_t level = 2; level > 0; --level) {
        const uint64_t pte_addr = table + indices[2 - level] * 8ULL;
        const uint64_t pte = bus.read64(pte_addr, MemoryAccessType::Read);

        if ((pte & PTE_V) == 0) {
            return makeFault(TRAP_PAGE_FAULT_NOT_PRESENT, AUX_SUBTYPE_NO_VALID_PTE, level);
        }

        // Support superpage leaves at L2 (1 GiB) and L1 (2 MiB).
        // Note: Little-64 permits non-aligned superpage bases (see paging-v1.md).
        if ((pte & (PTE_R | PTE_W | PTE_X)) != 0) {
            const uint64_t page_shift = (level == 2) ? 30ULL : 21ULL;
            return resolveLeaf(pte, level, page_shift);
        }

        if ((pte & PTE_RESERVED_MASK) != 0) {
            return makeFault(TRAP_PAGE_FAULT_RESERVED, AUX_SUBTYPE_RESERVED_BIT, level);
        }

        table = ((pte >> 10) << 12);
        if ((table & (PAGE_SIZE - 1ULL)) != 0) {
            return makeFault(TRAP_PAGE_FAULT_RESERVED, AUX_SUBTYPE_RESERVED_BIT, level);
        }
    }

    const uint64_t leaf_addr = table + idx0 * 8ULL;
    const uint64_t leaf = bus.read64(leaf_addr, MemoryAccessType::Read);

    if ((leaf & PTE_V) == 0)
        return makeFault(TRAP_PAGE_FAULT_NOT_PRESENT, AUX_SUBTYPE_NO_VALID_PTE, 0);

    if ((leaf & PTE_RESERVED_MASK) != 0)
        return makeFault(TRAP_PAGE_FAULT_RESERVED, AUX_SUBTYPE_RESERVED_BIT, 0);

    return resolveLeaf(leaf, 0, 12);
}
