#pragma once

#include "device.hpp"
#include "disk_image.hpp"
#include "interrupt_vectors.hpp"

#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

class MemoryBus;

class LiteSdCardDevice : public Device {
public:
    static constexpr uint64_t kReaderBase = 0x0000;
    static constexpr uint64_t kCoreBase = 0x0800;
    static constexpr uint64_t kIrqBase = 0x1000;
    static constexpr uint64_t kWriterBase = 0x1800;
    static constexpr uint64_t kPhyBase = 0x2000;
    static constexpr uint64_t kRegionSize = 0x2200;

    LiteSdCardDevice(uint64_t base, std::unique_ptr<DiskImage> image,
                     std::string_view name = "LITESDCARD",
                     uint64_t irq_line = Little64Vectors::kPvBlockIrqVector);

    void setMemoryBus(MemoryBus* bus) { _bus = bus; }
    DiskImage* image() const { return _image.get(); }

    uint8_t read8(uint64_t addr) override;
    void write8(uint64_t addr, uint8_t value) override;
    uint32_t read32(uint64_t addr) override;
    void write32(uint64_t addr, uint32_t value) override;

    void reset() override;
    std::string_view name() const override { return _name; }

private:
    struct DmaEngine {
        uint32_t base_hi = 0;
        uint32_t base_lo = 0;
        uint32_t length = 0;
        uint8_t enable = 0;
        uint8_t done = 0;

        uint64_t dmaBase() const {
            return (static_cast<uint64_t>(base_hi) << 32) | base_lo;
        }
    };

    static constexpr uint8_t kEventDone = 1U << 0;
    static constexpr uint8_t kEventWriteError = 1U << 1;
    static constexpr uint8_t kEventTimeout = 1U << 2;
    static constexpr uint8_t kEventCrcError = 1U << 3;

    static constexpr uint8_t kRespNone = 0;
    static constexpr uint8_t kRespShort = 1;
    static constexpr uint8_t kRespLong = 2;
    static constexpr uint8_t kRespShortBusy = 3;

    static constexpr uint8_t kTransferNone = 0;
    static constexpr uint8_t kTransferRead = 1;
    static constexpr uint8_t kTransferWrite = 2;

    static constexpr uint32_t kIrqCardDetect = 1U << 0;
    static constexpr uint32_t kIrqReadDone = 1U << 1;
    static constexpr uint32_t kIrqWriteDone = 1U << 2;
    static constexpr uint32_t kIrqCmdDone = 1U << 3;

    void _updateInterruptLine();
    void _setPendingIrq(uint32_t bits);
    void _clearPendingIrq(uint32_t bits);

    void _clearTransferState();
    void _prepareShortResponse(uint32_t value);
    void _prepareLongResponse(const std::array<uint32_t, 4>& value);
    void _completeCommand(uint8_t cmd_event, uint8_t data_event, uint32_t irq_bits);
    void _completeCommandError(uint8_t cmd_event, uint8_t data_event, uint32_t irq_bits);
    void _handleCommandSend();

    bool _copyToGuest(uint64_t guest_phys, const uint8_t* data, size_t len) const;
    bool _copyFromGuest(uint64_t guest_phys, uint8_t* data, size_t len) const;
    uint32_t _transferLength() const;
    bool _runReadTransfer(uint32_t command, uint32_t argument);
    bool _runWriteTransfer(uint32_t command, uint32_t argument);

    std::array<uint32_t, 4> _cidResponse() const;
    std::array<uint32_t, 4> _csdResponse() const;
    std::vector<uint8_t> _scrPayload() const;
    std::vector<uint8_t> _switchStatusPayload(bool set_mode) const;
    std::vector<uint8_t> _sdStatusPayload() const;

    std::string _name;
    std::unique_ptr<DiskImage> _image;
    MemoryBus* _bus = nullptr;

    DmaEngine _reader;
    DmaEngine _writer;

    uint32_t _cmd_argument = 0;
    uint32_t _cmd_command = 0;
    std::array<uint32_t, 4> _cmd_response{};
    uint8_t _cmd_event = 0;
    uint8_t _data_event = 0;
    uint16_t _block_length = 512;
    uint32_t _block_count = 1;
    uint32_t _clock_divider = 256;
    uint32_t _phy_initialize = 0;
    uint32_t _phy_settings = 0;

    uint32_t _irq_pending = 0;
    uint32_t _irq_enable = 0;

    bool _app_cmd_pending = false;
    bool _card_selected = false;
    bool _wide_bus = false;
    bool _high_speed = false;
    uint16_t _rca = 1;
};