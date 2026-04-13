#pragma once

#include "special_register_layout.hpp"

#include <cstdint>

namespace Little64RegisterLayout {

inline constexpr uint64_t kGeneralPurposeRegisterCount = 16;

inline constexpr uint64_t kArgument5Index = 6;
inline constexpr uint64_t kArgument4Index = 7;
inline constexpr uint64_t kArgument3Index = 8;
inline constexpr uint64_t kArgument2Index = 9;
inline constexpr uint64_t kArgument1Index = 10;
inline constexpr uint64_t kFramePointerIndex = 11;
inline constexpr uint64_t kStackPointerIndex = 13;
inline constexpr uint64_t kLinkRegisterIndex = 14;
inline constexpr uint64_t kProgramCounterIndex = 15;

inline constexpr uint64_t kFlagsIndex = kGeneralPurposeRegisterCount;
inline constexpr uint64_t kFirstSpecialRegisterIndex = kFlagsIndex + 1;
inline constexpr uint64_t kVisibleSpecialRegisterCount = Little64SpecialRegisters::kVisibleDebugRegisterCount;
inline constexpr uint64_t kTotalRegisterCount = kFirstSpecialRegisterIndex + kVisibleSpecialRegisterCount;

} // namespace Little64RegisterLayout