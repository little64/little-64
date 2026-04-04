#include "address_translator.hpp"

namespace {

constexpr uint64_t PTE_V = 1ULL << 0;
constexpr uint64_t PTE_R = 1ULL << 1;
constexpr uint64_t PTE_W = 1ULL << 2;
constexpr uint64_t PTE_X = 1ULL << 3;
constexpr uint64_t PTE_U = 1ULL << 4;
constexpr uint64_t PTE_A = 1ULL << 6;
constexpr uint64_t PTE_D = 1ULL << 7;

constexpr uint64_t PTE_RESERVED_MASK = 0xFFC0000000000000ULL; // bits [63:54]

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
    if (access == PagingAccessType::Execute && (virtual_addr & 0x1ULL)) {
        return PagingTranslateResult{
            .valid = false,
            .physical = 0,
            .trap_cause = TRAP_EXEC_ALIGN,
            .trap_aux = _encodeAux(AUX_SUBTYPE_NONE, 0),
        };
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
        return PagingTranslateResult{
            .valid = false,
            .physical = 0,
            .trap_cause = TRAP_PAGE_FAULT_RESERVED,
            .trap_aux = _encodeAux(AUX_SUBTYPE_RESERVED_BIT, 2),
        };
    }

    if (!_isCanonical39(virtual_addr)) {
        return PagingTranslateResult{
            .valid = false,
            .physical = 0,
            .trap_cause = TRAP_PAGE_FAULT_CANONICAL,
            .trap_aux = _encodeAux(AUX_SUBTYPE_CANONICAL, 2),
        };
    }

    const uint64_t idx2 = (virtual_addr >> 30) & 0x1FFULL;
    const uint64_t idx1 = (virtual_addr >> 21) & 0x1FFULL;
    const uint64_t idx0 = (virtual_addr >> 12) & 0x1FFULL;
    const uint64_t page_off = virtual_addr & 0xFFFULL;

    uint64_t table = config.root_table_physical;
    const uint64_t indices[3] = { idx2, idx1, idx0 };

    for (uint64_t level = 2; level > 0; --level) {
        const uint64_t pte_addr = table + indices[2 - level] * 8ULL;
        const uint64_t pte = bus.read64(pte_addr, MemoryAccessType::Read);

        if ((pte & PTE_V) == 0) {
            return PagingTranslateResult{
                .valid = false,
                .physical = 0,
                .trap_cause = TRAP_PAGE_FAULT_NOT_PRESENT,
                .trap_aux = _encodeAux(AUX_SUBTYPE_NO_VALID_PTE, level),
            };
        }

        if ((pte & PTE_RESERVED_MASK) != 0) {
            return PagingTranslateResult{
                .valid = false,
                .physical = 0,
                .trap_cause = TRAP_PAGE_FAULT_RESERVED,
                .trap_aux = _encodeAux(AUX_SUBTYPE_RESERVED_BIT, level),
            };
        }

        if ((pte & (PTE_R | PTE_W | PTE_X)) != 0) {
            return PagingTranslateResult{
                .valid = false,
                .physical = 0,
                .trap_cause = TRAP_PAGE_FAULT_RESERVED,
                .trap_aux = _encodeAux(AUX_SUBTYPE_INVALID_NONLEAF, level),
            };
        }

        table = ((pte >> 10) << 12);
        if ((table & (PAGE_SIZE - 1ULL)) != 0) {
            return PagingTranslateResult{
                .valid = false,
                .physical = 0,
                .trap_cause = TRAP_PAGE_FAULT_RESERVED,
                .trap_aux = _encodeAux(AUX_SUBTYPE_RESERVED_BIT, level),
            };
        }
    }

    const uint64_t leaf_addr = table + idx0 * 8ULL;
    const uint64_t leaf = bus.read64(leaf_addr, MemoryAccessType::Read);

    if ((leaf & PTE_V) == 0) {
        return PagingTranslateResult{
            .valid = false,
            .physical = 0,
            .trap_cause = TRAP_PAGE_FAULT_NOT_PRESENT,
            .trap_aux = _encodeAux(AUX_SUBTYPE_NO_VALID_PTE, 0),
        };
    }

    if ((leaf & PTE_RESERVED_MASK) != 0) {
        return PagingTranslateResult{
            .valid = false,
            .physical = 0,
            .trap_cause = TRAP_PAGE_FAULT_RESERVED,
            .trap_aux = _encodeAux(AUX_SUBTYPE_RESERVED_BIT, 0),
        };
    }

    if ((leaf & (PTE_R | PTE_W | PTE_X)) == 0) {
        return PagingTranslateResult{
            .valid = false,
            .physical = 0,
            .trap_cause = TRAP_PAGE_FAULT_NOT_PRESENT,
            .trap_aux = _encodeAux(AUX_SUBTYPE_NO_VALID_PTE, 0),
        };
    }

    bool permission_ok = false;
    switch (access) {
        case PagingAccessType::Read:
            permission_ok = (leaf & PTE_R) != 0;
            break;
        case PagingAccessType::Write:
            permission_ok = (leaf & PTE_W) != 0;
            break;
        case PagingAccessType::Execute:
            permission_ok = (leaf & PTE_X) != 0;
            break;
    }

    if (!permission_ok) {
        return PagingTranslateResult{
            .valid = false,
            .physical = 0,
            .trap_cause = TRAP_PAGE_FAULT_PERMISSION,
            .trap_aux = _encodeAux(AUX_SUBTYPE_PERMISSION, 0),
        };
    }

    // User mode can only access pages marked with PTE_U
    if (config.is_user && !(leaf & PTE_U)) {
        return PagingTranslateResult{
            .valid = false,
            .physical = 0,
            .trap_cause = TRAP_PAGE_FAULT_PERMISSION,
            .trap_aux = _encodeAux(AUX_SUBTYPE_PERMISSION, 0),
        };
    }

    const uint64_t page_base = ((leaf >> 10) << 12);
    return PagingTranslateResult{
        .valid = true,
        .physical = page_base + page_off,
        .trap_cause = 0,
        .trap_aux = 0,
    };
}
