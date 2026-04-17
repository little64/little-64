#pragma once

#include "device.hpp"

#include <array>
#include <cstdint>
#include <string>
#include <string_view>

class LiteDramDfiiStubDevice : public Device {
public:
    static constexpr uint64_t kSize = 0x100;

    static constexpr uint64_t kControlOffset = 0x00;
    static constexpr uint64_t kPhase0CommandOffset = 0x04;
    static constexpr uint64_t kPhase0CommandIssueOffset = 0x08;
    static constexpr uint64_t kPhase0AddressOffset = 0x0C;
    static constexpr uint64_t kPhase0BankAddressOffset = 0x10;
    static constexpr uint64_t kPhaseStride = 0x30;
    static constexpr uint32_t kControlHardwareMode = 0x01;

    explicit LiteDramDfiiStubDevice(uint64_t base,
                                    std::string_view name = "LITEDRAM");

    uint8_t read8(uint64_t addr) override;
    void write8(uint64_t addr, uint8_t value) override;
    uint32_t read32(uint64_t addr) override;
    void write32(uint64_t addr, uint32_t value) override;

    void reset() override;
    std::string_view name() const override { return _name; }

private:
    static constexpr size_t kRegisterCount = static_cast<size_t>(kSize / 4);

    bool isReadOnlyOffset(uint64_t offset) const;

    std::string _name;
    std::array<uint32_t, kRegisterCount> _registers{};
};