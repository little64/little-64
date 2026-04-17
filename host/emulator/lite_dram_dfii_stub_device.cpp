#include "lite_dram_dfii_stub_device.hpp"

LiteDramDfiiStubDevice::LiteDramDfiiStubDevice(uint64_t base, std::string_view name)
    : Device(base, kSize), _name(name) {
    reset();
}

void LiteDramDfiiStubDevice::reset() {
    _registers.fill(0);
    _registers[kControlOffset / 4] = kControlHardwareMode;
}

bool LiteDramDfiiStubDevice::isReadOnlyOffset(uint64_t offset) const {
    const uint64_t phase_offset = offset % kPhaseStride;
    return phase_offset >= 0x20 && phase_offset < 0x30;
}

uint8_t LiteDramDfiiStubDevice::read8(uint64_t addr) {
    const uint64_t aligned = addr & ~0x3ULL;
    const uint32_t shift = static_cast<uint32_t>((addr & 0x3ULL) * 8);
    return static_cast<uint8_t>((read32(aligned) >> shift) & 0xFFU);
}

void LiteDramDfiiStubDevice::write8(uint64_t addr, uint8_t value) {
    const uint64_t aligned = addr & ~0x3ULL;
    const uint32_t shift = static_cast<uint32_t>((addr & 0x3ULL) * 8);
    uint32_t current = read32(aligned);
    current &= ~(0xFFU << shift);
    current |= static_cast<uint32_t>(value) << shift;
    write32(aligned, current);
}

uint32_t LiteDramDfiiStubDevice::read32(uint64_t addr) {
    const uint64_t offset = addr - base();
    if (offset >= kSize || (offset & 0x3ULL) != 0) {
        return 0;
    }
    return _registers[static_cast<size_t>(offset / 4)];
}

void LiteDramDfiiStubDevice::write32(uint64_t addr, uint32_t value) {
    const uint64_t offset = addr - base();
    if (offset >= kSize || (offset & 0x3ULL) != 0 || isReadOnlyOffset(offset)) {
        return;
    }

    _registers[static_cast<size_t>(offset / 4)] = value;
}