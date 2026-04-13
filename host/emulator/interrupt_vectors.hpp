#pragma once

#include <cstddef>
#include <cstdint>

namespace Little64Vectors {

constexpr uint64_t kNoTrap = 0;

constexpr uint64_t kTrapExecAlign = 1;
constexpr uint64_t kTrapPrivilegedInstruction = 2;
constexpr uint64_t kTrapSyscall = 3;
constexpr uint64_t kTrapSyscallFromSupervisor = 4;
constexpr uint64_t kTrapPageFaultNotPresent = 5;
constexpr uint64_t kTrapPageFaultPermission = 6;
constexpr uint64_t kTrapPageFaultReserved = 7;
constexpr uint64_t kTrapPageFaultCanonical = 8;

constexpr uint64_t kFirstExceptionVector = kTrapExecAlign;
constexpr uint64_t kLastExceptionVector = kTrapPageFaultCanonical;

constexpr uint64_t kReservedVector = 64;
constexpr uint64_t kIrqVectorBase = 65;
constexpr uint64_t kMaxVector = 127;
constexpr size_t kInterruptBankCount = 2;
constexpr uint64_t kInterruptBankWidth = 64;

constexpr uint64_t kSerialIrqVector = 65;
constexpr uint64_t kTimerIrqVector = 66;
constexpr uint64_t kPvBlockIrqVector = 67;
constexpr uint64_t kUiTestIrqVector = kSerialIrqVector;

constexpr bool isExceptionVector(uint64_t vector) {
    return vector >= kFirstExceptionVector && vector <= kLastExceptionVector;
}

constexpr bool isIrqVector(uint64_t vector) {
    return vector >= kIrqVectorBase && vector <= kMaxVector;
}

constexpr size_t interruptBankForVector(uint64_t vector) {
    return static_cast<size_t>(vector / kInterruptBankWidth);
}

constexpr uint64_t interruptBitForVector(uint64_t vector) {
    return 1ULL << (vector % kInterruptBankWidth);
}

constexpr uint64_t validIrqMaskForBank(size_t bank) {
    return bank == 1 ? ~1ULL : 0ULL;
}

} // namespace Little64Vectors