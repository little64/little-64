#pragma once

#include <array>
#include <cstdint>

namespace Little64SpecialRegisters {

inline constexpr uint64_t kSelectorMask = 0xFFFF;
inline constexpr uint64_t kUserBankBit = 0x8000;
inline constexpr uint64_t kBankLocalIndexMask = 0x7FFF;

inline constexpr uint64_t kCpuControl = 0;

inline constexpr uint64_t kPageTableRootPhysical = 11;
inline constexpr uint64_t kBootInfoFramePhysical = 12;
inline constexpr uint64_t kBootSourcePageSize = 13;
inline constexpr uint64_t kBootSourcePageCount = 14;
inline constexpr uint64_t kHypercallCaps = 15;

inline constexpr uint64_t kFirstInterruptRegister = 16;
inline constexpr uint64_t kInterruptTableBase = 16;
inline constexpr uint64_t kInterruptMask = 17;
inline constexpr uint64_t kInterruptMaskHigh = 18;
inline constexpr uint64_t kInterruptStates = 19;
inline constexpr uint64_t kInterruptStatesHigh = 20;
inline constexpr uint64_t kInterruptEpc = 21;
inline constexpr uint64_t kInterruptEflags = 22;
inline constexpr uint64_t kInterruptCpuControl = 23;
inline constexpr uint64_t kTrapCause = 24;
inline constexpr uint64_t kTrapFaultAddr = 25;
inline constexpr uint64_t kTrapAccess = 26;
inline constexpr uint64_t kTrapPc = 27;
inline constexpr uint64_t kTrapAux = 28;
inline constexpr uint64_t kLastInterruptRegister = kTrapAux;

inline constexpr uint64_t kUserThreadPointer = kUserBankBit | 0;

inline constexpr uint64_t kCount = kLastInterruptRegister + 1;

inline constexpr std::array<uint64_t, kCount + 1> kDebugVisibleSelectors = {
    kCpuControl,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    kPageTableRootPhysical,
    kBootInfoFramePhysical,
    kBootSourcePageSize,
    kBootSourcePageCount,
    kHypercallCaps,
    kInterruptTableBase,
    kInterruptMask,
    kInterruptMaskHigh,
    kInterruptStates,
    kInterruptStatesHigh,
    kInterruptEpc,
    kInterruptEflags,
    kInterruptCpuControl,
    kTrapCause,
    kTrapFaultAddr,
    kTrapAccess,
    kTrapPc,
    kTrapAux,
    kUserThreadPointer,
};

inline constexpr uint64_t kVisibleDebugRegisterCount = kDebugVisibleSelectors.size();

constexpr uint64_t normalizeSelector(uint64_t selector) {
    return selector & kSelectorMask;
}

constexpr bool isUserBankSelector(uint64_t selector) {
    return (normalizeSelector(selector) & kUserBankBit) != 0;
}

constexpr bool isUserAccessibleSelector(uint64_t selector) {
    return normalizeSelector(selector) == kUserThreadPointer;
}

constexpr uint64_t selectorForDebugOrdinal(uint64_t ordinal) {
    return ordinal < kVisibleDebugRegisterCount ? kDebugVisibleSelectors[ordinal] : kSelectorMask;
}

constexpr const char* nameForSelector(uint64_t selector) {
    switch (normalizeSelector(selector)) {
        case kCpuControl: return "cpu_control";
        case kPageTableRootPhysical: return "page_table_root_physical";
        case kBootInfoFramePhysical: return "boot_info_frame_physical";
        case kBootSourcePageSize: return "boot_source_page_size";
        case kBootSourcePageCount: return "boot_source_page_count";
        case kHypercallCaps: return "hypercall_caps";
        case kInterruptTableBase: return "interrupt_table_base";
        case kInterruptMask: return "interrupt_mask";
        case kInterruptMaskHigh: return "interrupt_mask_high";
        case kInterruptStates: return "interrupt_states";
        case kInterruptStatesHigh: return "interrupt_states_high";
        case kInterruptEpc: return "interrupt_epc";
        case kInterruptEflags: return "interrupt_eflags";
        case kInterruptCpuControl: return "interrupt_cpu_control";
        case kTrapCause: return "trap_cause";
        case kTrapFaultAddr: return "trap_fault_addr";
        case kTrapAccess: return "trap_access";
        case kTrapPc: return "trap_pc";
        case kTrapAux: return "trap_aux";
        case kUserThreadPointer: return "thread_pointer";
        default: return nullptr;
    }
}

} // namespace Little64SpecialRegisters