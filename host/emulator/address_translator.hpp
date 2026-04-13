#pragma once

#include "interrupt_vectors.hpp"
#include "memory_bus.hpp"

#include <cstdint>

enum class PagingAccessType : uint8_t {
    Read = 0,
    Write = 1,
    Execute = 2,
};

struct PagingConfig {
    bool enabled = false;
    uint64_t root_table_physical = 0;
    bool is_user = false;          // true when CPU is in user mode
};

struct PagingTranslateResult {
    bool valid = true;
    uint64_t physical = 0;
    uint64_t trap_cause = 0;
    uint64_t trap_aux = 0;
};

class AddressTranslator {
public:
    static constexpr uint64_t PAGE_SIZE = 4096;

    static constexpr uint64_t TRAP_EXEC_ALIGN = Little64Vectors::kTrapExecAlign;
    static constexpr uint64_t TRAP_PRIVILEGED_INSTRUCTION = Little64Vectors::kTrapPrivilegedInstruction;
    static constexpr uint64_t TRAP_SYSCALL = Little64Vectors::kTrapSyscall;
    static constexpr uint64_t TRAP_SYSCALL_FROM_SUPERVISOR = Little64Vectors::kTrapSyscallFromSupervisor;
    static constexpr uint64_t TRAP_PAGE_FAULT_BASE = Little64Vectors::kTrapPageFaultNotPresent;
    static constexpr uint64_t TRAP_PAGE_FAULT_NOT_PRESENT = Little64Vectors::kTrapPageFaultNotPresent;
    static constexpr uint64_t TRAP_PAGE_FAULT_PERMISSION = Little64Vectors::kTrapPageFaultPermission;
    static constexpr uint64_t TRAP_PAGE_FAULT_RESERVED = Little64Vectors::kTrapPageFaultReserved;
    static constexpr uint64_t TRAP_PAGE_FAULT_CANONICAL = Little64Vectors::kTrapPageFaultCanonical;
    static constexpr uint64_t TRAP_INVALID_INSTRUCTION = Little64Vectors::kTrapInvalidInstruction;

    static constexpr uint64_t AUX_SUBTYPE_NONE = 0;
    static constexpr uint64_t AUX_SUBTYPE_NO_VALID_PTE = 1;
    static constexpr uint64_t AUX_SUBTYPE_INVALID_NONLEAF = 2;
    static constexpr uint64_t AUX_SUBTYPE_PERMISSION = 3;
    static constexpr uint64_t AUX_SUBTYPE_RESERVED_BIT = 4;
    static constexpr uint64_t AUX_SUBTYPE_CANONICAL = 5;

    PagingTranslateResult translate(const MemoryBus& bus,
                                    const PagingConfig& config,
                                    uint64_t virtual_addr,
                                    PagingAccessType access) const;

private:
    static bool _isCanonical39(uint64_t addr);
    static uint64_t _encodeAux(uint64_t subtype, uint64_t level);
};
