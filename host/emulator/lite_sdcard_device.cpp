#include "lite_sdcard_device.hpp"

#include "memory_bus.hpp"

#include <algorithm>
#include <cstring>

namespace {

unsigned __int128 set_response_bits(unsigned __int128 value, int start, int size, uint32_t field) {
    if (size <= 0) {
        return value;
    }

    unsigned __int128 mask = (size >= 32)
        ? ((static_cast<unsigned __int128>(1) << 32) - 1)
        : ((static_cast<unsigned __int128>(1) << size) - 1);
    const unsigned __int128 shifted_mask = mask << start;
    value &= ~shifted_mask;
    value |= (static_cast<unsigned __int128>(field) & mask) << start;
    return value;
}

std::array<uint32_t, 4> split_response(unsigned __int128 value) {
    return {
        static_cast<uint32_t>(value >> 96),
        static_cast<uint32_t>(value >> 64),
        static_cast<uint32_t>(value >> 32),
        static_cast<uint32_t>(value),
    };
}

std::vector<uint8_t> to_big_endian_bytes(uint64_t value) {
    std::vector<uint8_t> out(8, 0);
    for (size_t i = 0; i < out.size(); ++i) {
        out[i] = static_cast<uint8_t>(value >> ((out.size() - 1 - i) * 8));
    }
    return out;
}

} // namespace

LiteSdCardDevice::LiteSdCardDevice(uint64_t base, std::unique_ptr<DiskImage> image,
                                   std::string_view name, uint64_t irq_line)
    : Device(base, kRegionSize), _name(name), _image(std::move(image)) {
    setInterruptLine(static_cast<int>(irq_line));
    reset();
}

void LiteSdCardDevice::reset() {
    _reader = {};
    _writer = {};
    _cmd_argument = 0;
    _cmd_command = 0;
    _cmd_response = {};
    _cmd_event = 0;
    _data_event = 0;
    _block_length = 512;
    _block_count = 1;
    _clock_divider = 256;
    _phy_initialize = 0;
    _phy_settings = 0;
    _irq_pending = 0;
    _irq_enable = 0;
    _app_cmd_pending = false;
    _card_selected = false;
    _wide_bus = false;
    _high_speed = false;
    _rca = 1;
    clearInterruptLine();
}

uint8_t LiteSdCardDevice::read8(uint64_t addr) {
    return static_cast<uint8_t>((read32(addr & ~0x3ULL) >> ((addr & 0x3ULL) * 8)) & 0xFFU);
}

void LiteSdCardDevice::write8(uint64_t addr, uint8_t value) {
    const uint64_t aligned = addr & ~0x3ULL;
    const uint32_t shift = static_cast<uint32_t>((addr & 0x3ULL) * 8);
    uint32_t current = read32(aligned);
    current &= ~(0xFFU << shift);
    current |= static_cast<uint32_t>(value) << shift;
    write32(aligned, current);
}

uint32_t LiteSdCardDevice::read32(uint64_t addr) {
    const uint64_t offset = addr - base();
    switch (offset) {
        case kReaderBase + 0x00: return _reader.base_hi;
        case kReaderBase + 0x04: return _reader.base_lo;
        case kReaderBase + 0x08: return _reader.length;
        case kReaderBase + 0x0C: return _reader.enable;
        case kReaderBase + 0x10: return _reader.done;
        case kCoreBase + 0x00: return _cmd_argument;
        case kCoreBase + 0x04: return _cmd_command;
        case kCoreBase + 0x0C: return _cmd_response[0];
        case kCoreBase + 0x10: return _cmd_response[1];
        case kCoreBase + 0x14: return _cmd_response[2];
        case kCoreBase + 0x18: return _cmd_response[3];
        case kCoreBase + 0x1C: return _cmd_event;
        case kCoreBase + 0x20: return _data_event;
        case kCoreBase + 0x24: return _block_length;
        case kCoreBase + 0x28: return _block_count;
        case kIrqBase + 0x00: return _irq_pending;
        case kIrqBase + 0x04: return _irq_pending;
        case kIrqBase + 0x08: return _irq_enable;
        case kWriterBase + 0x00: return _writer.base_hi;
        case kWriterBase + 0x04: return _writer.base_lo;
        case kWriterBase + 0x08: return _writer.length;
        case kWriterBase + 0x0C: return _writer.enable;
        case kWriterBase + 0x10: return _writer.done;
        case kPhyBase + 0x00:
            return (_image && _image->isValid()) ? 0U : 1U;
        case kPhyBase + 0x04: return _clock_divider;
        case kPhyBase + 0x08: return _phy_initialize;
        case kPhyBase + 0x0C:
        case kPhyBase + 0x10:
            return (_image && _image->isValid() && !_image->isReadOnly()) ? 0U : 1U;
        case kPhyBase + 0x18: return _phy_settings;
        default:
            return 0;
    }
}

void LiteSdCardDevice::write32(uint64_t addr, uint32_t value) {
    const uint64_t offset = addr - base();
    switch (offset) {
        case kReaderBase + 0x00:
            _reader.base_hi = value;
            return;
        case kReaderBase + 0x04:
            _reader.base_lo = value;
            return;
        case kReaderBase + 0x08:
            _reader.length = value;
            return;
        case kReaderBase + 0x0C:
            _reader.enable = static_cast<uint8_t>(value & 0x1U);
            if (_reader.enable == 0) {
                _reader.done = 0;
            }
            return;
        case kCoreBase + 0x00:
            _cmd_argument = value;
            return;
        case kCoreBase + 0x04:
            _cmd_command = value;
            return;
        case kCoreBase + 0x08:
            if ((value & 0x1U) != 0) {
                _handleCommandSend();
            }
            return;
        case kCoreBase + 0x1C:
            _cmd_event &= ~static_cast<uint8_t>(value & 0xFFU);
            return;
        case kCoreBase + 0x20:
            _data_event &= ~static_cast<uint8_t>(value & 0xFFU);
            return;
        case kCoreBase + 0x24:
            _block_length = static_cast<uint16_t>(value & 0xFFFFU);
            return;
        case kCoreBase + 0x28:
            _block_count = value == 0 ? 1U : value;
            return;
        case kIrqBase + 0x04:
            _clearPendingIrq(value);
            return;
        case kIrqBase + 0x08:
            _irq_enable = value;
            _updateInterruptLine();
            return;
        case kWriterBase + 0x00:
            _writer.base_hi = value;
            return;
        case kWriterBase + 0x04:
            _writer.base_lo = value;
            return;
        case kWriterBase + 0x08:
            _writer.length = value;
            return;
        case kWriterBase + 0x0C:
            _writer.enable = static_cast<uint8_t>(value & 0x1U);
            if (_writer.enable == 0) {
                _writer.done = 0;
            }
            return;
        case kPhyBase + 0x04:
            _clock_divider = value;
            return;
        case kPhyBase + 0x08:
            _phy_initialize = value;
            return;
        case kPhyBase + 0x18:
            _phy_settings = value;
            return;
        default:
            return;
    }
}

void LiteSdCardDevice::_updateInterruptLine() {
    if ((_irq_pending & _irq_enable) != 0) {
        assertInterruptLine();
    } else {
        clearInterruptLine();
    }
}

void LiteSdCardDevice::_setPendingIrq(uint32_t bits) {
    _irq_pending |= bits;
    _updateInterruptLine();
}

void LiteSdCardDevice::_clearPendingIrq(uint32_t bits) {
    _irq_pending &= ~bits;
    _updateInterruptLine();
}

void LiteSdCardDevice::_clearTransferState() {
    _cmd_event = 0;
    _data_event = 0;
    _reader.done = 0;
    _writer.done = 0;
}

void LiteSdCardDevice::_prepareShortResponse(uint32_t value) {
    _cmd_response = {0, 0, 0, value};
}

void LiteSdCardDevice::_prepareLongResponse(const std::array<uint32_t, 4>& value) {
    _cmd_response = value;
}

void LiteSdCardDevice::_completeCommand(uint8_t cmd_event, uint8_t data_event, uint32_t irq_bits) {
    _cmd_event = cmd_event;
    _data_event = data_event;
    _setPendingIrq(irq_bits | kIrqCmdDone);
}

void LiteSdCardDevice::_completeCommandError(uint8_t cmd_event, uint8_t data_event, uint32_t irq_bits) {
    _cmd_event = cmd_event;
    _data_event = data_event;
    _setPendingIrq(irq_bits | kIrqCmdDone);
}

bool LiteSdCardDevice::_copyToGuest(uint64_t guest_phys, const uint8_t* data, size_t len) const {
    if (!_bus) {
        return false;
    }
    for (size_t i = 0; i < len; ++i) {
        _bus->write8(guest_phys + i, data[i], MemoryAccessType::Write);
    }
    return true;
}

bool LiteSdCardDevice::_copyFromGuest(uint64_t guest_phys, uint8_t* data, size_t len) const {
    if (!_bus) {
        return false;
    }
    for (size_t i = 0; i < len; ++i) {
        data[i] = _bus->read8(guest_phys + i, MemoryAccessType::Read);
    }
    return true;
}

uint32_t LiteSdCardDevice::_transferLength() const {
    const uint32_t blocks = _block_count == 0 ? 1U : _block_count;
    const uint32_t block_length = _block_length == 0 ? 512U : _block_length;
    return block_length * blocks;
}

bool LiteSdCardDevice::_runReadTransfer(uint32_t command, uint32_t argument) {
    if ((command == 17U || command == 18U) && (!_reader.enable || !_bus)) {
        return false;
    }

    std::vector<uint8_t> payload;
    uint32_t irq_bits = kIrqReadDone;

    if (command == 17U || command == 18U) {
        if (!_image || !_image->isValid()) {
            return false;
        }
        payload.resize(_reader.length == 0 ? _transferLength() : _reader.length, 0);
        if (!_image->read(static_cast<uint64_t>(argument) * DiskImage::kSectorSize,
                          payload.data(), payload.size(), nullptr)) {
            return false;
        }
    } else if (command == 51U) {
        payload = _scrPayload();
    } else if (command == 6U) {
        payload = _switchStatusPayload((_cmd_argument & 0x80000000U) != 0);
    } else if (command == 13U) {
        payload = _sdStatusPayload();
    } else {
        return false;
    }

    if (_reader.enable && !payload.empty()) {
        if (!_bus || !_copyToGuest(_reader.dmaBase(), payload.data(), payload.size())) {
            return false;
        }
        _reader.done = kEventDone;
    }

    _completeCommand(kEventDone, kEventDone, irq_bits);
    return true;
}

bool LiteSdCardDevice::_runWriteTransfer(uint32_t command, uint32_t argument) {
    if ((command != 24U && command != 25U) || !_writer.enable || !_bus || !_image || !_image->isValid()) {
        return false;
    }

    const size_t length = _writer.length == 0 ? _transferLength() : _writer.length;
    std::vector<uint8_t> payload(length, 0);
    if (!_copyFromGuest(_writer.dmaBase(), payload.data(), payload.size())) {
        return false;
    }
    if (!_image->write(static_cast<uint64_t>(argument) * DiskImage::kSectorSize,
                       payload.data(), payload.size(), nullptr)) {
        return false;
    }
    _image->flush(nullptr);
    _writer.done = kEventDone;
    _completeCommand(kEventDone, kEventDone, kIrqWriteDone);
    return true;
}

std::array<uint32_t, 4> LiteSdCardDevice::_cidResponse() const {
    unsigned __int128 value = 0;
    value = set_response_bits(value, 120, 8, 0x42);
    value = set_response_bits(value, 104, 16, 0x4C36);
    value = set_response_bits(value, 96, 8, 'E');
    value = set_response_bits(value, 88, 8, 'M');
    value = set_response_bits(value, 80, 8, 'U');
    value = set_response_bits(value, 72, 8, '6');
    value = set_response_bits(value, 64, 8, '4');
    value = set_response_bits(value, 60, 4, 1);
    value = set_response_bits(value, 56, 4, 0);
    value = set_response_bits(value, 24, 32, 0x12345678U);
    value = set_response_bits(value, 12, 8, 24);
    value = set_response_bits(value, 8, 4, 4);
    return split_response(value);
}

std::array<uint32_t, 4> LiteSdCardDevice::_csdResponse() const {
    const uint64_t sectors = (_image && _image->isValid()) ? _image->sectorCount() : 0;
    const uint32_t c_size = sectors >= 1024 ? static_cast<uint32_t>((sectors / 1024) - 1) : 0;

    unsigned __int128 value = 0;
    value = set_response_bits(value, 126, 2, 1);
    value = set_response_bits(value, 99, 4, 11);
    value = set_response_bits(value, 96, 3, 2);
    value = set_response_bits(value, 84, 12, 0x5B5);
    value = set_response_bits(value, 80, 4, 9);
    value = set_response_bits(value, 48, 22, c_size);
    return split_response(value);
}

std::vector<uint8_t> LiteSdCardDevice::_scrPayload() const {
    uint64_t value = 0;
    value |= static_cast<uint64_t>(2U) << 56;
    value |= static_cast<uint64_t>(0x5U) << 48;
    value |= static_cast<uint64_t>(1U) << 55;
    return to_big_endian_bytes(value);
}

std::vector<uint8_t> LiteSdCardDevice::_switchStatusPayload(bool set_mode) const {
    std::vector<uint8_t> payload(64, 0);
    payload[13] = 0x01;
    payload[16] = static_cast<uint8_t>(set_mode ? 0x01 : (_high_speed ? 0x01 : 0x00));
    return payload;
}

std::vector<uint8_t> LiteSdCardDevice::_sdStatusPayload() const {
    return std::vector<uint8_t>(64, 0);
}

void LiteSdCardDevice::_handleCommandSend() {
    _clearTransferState();

    const uint32_t command = (_cmd_command >> 8) & 0x3FU;
    const uint8_t response_type = static_cast<uint8_t>(_cmd_command & 0x3U);
    const uint8_t transfer = static_cast<uint8_t>((_cmd_command >> 5) & 0x3U);
    const bool app_cmd = _app_cmd_pending;
    _app_cmd_pending = false;

    switch (command) {
        case 0:
            _card_selected = false;
            _wide_bus = false;
            _high_speed = false;
            _prepareShortResponse(0);
            _completeCommand(kEventDone, 0, 0);
            return;
        case 2:
        case 10:
            _prepareLongResponse(_cidResponse());
            _completeCommand(kEventDone, 0, 0);
            return;
        case 3:
            _prepareShortResponse(static_cast<uint32_t>(_rca) << 16);
            _completeCommand(kEventDone, 0, 0);
            return;
        case 6:
            if (app_cmd) {
                _wide_bus = (_cmd_argument & 0x3U) == 2U;
                _prepareShortResponse(0);
                _completeCommand(kEventDone, 0, 0);
                return;
            }
            _prepareShortResponse(0);
            if (transfer == kTransferRead && _runReadTransfer(command, _cmd_argument)) {
                if ((_cmd_argument & 0x80000000U) != 0) {
                    _high_speed = true;
                }
                return;
            }
            break;
        case 7:
            _card_selected = true;
            _prepareShortResponse(0);
            _completeCommand(kEventDone, 0, 0);
            return;
        case 8:
            _prepareShortResponse(_cmd_argument & 0xFFFU);
            _completeCommand(kEventDone, 0, 0);
            return;
        case 9:
            _prepareLongResponse(_csdResponse());
            _completeCommand(kEventDone, 0, 0);
            return;
        case 12:
            _prepareShortResponse(0);
            _completeCommand(kEventDone, 0, 0);
            return;
        case 13:
            _prepareShortResponse(0);
            if (app_cmd && transfer == kTransferRead && _runReadTransfer(command, _cmd_argument)) {
                return;
            }
            _prepareShortResponse(0);
            _completeCommand(kEventDone, 0, 0);
            return;
        case 16:
            _prepareShortResponse(0);
            _completeCommand(kEventDone, 0, 0);
            return;
        case 17:
        case 18:
            _prepareShortResponse(0);
            if (_runReadTransfer(command, _cmd_argument)) {
                return;
            }
            break;
        case 24:
        case 25:
            _prepareShortResponse(0);
            if (_runWriteTransfer(command, _cmd_argument)) {
                return;
            }
            break;
        case 41:
            if (app_cmd) {
                _prepareShortResponse(0xC0FF8000U);
                _completeCommand(kEventDone, 0, 0);
                return;
            }
            break;
        case 51:
            _prepareShortResponse(0);
            if (app_cmd && transfer == kTransferRead && _runReadTransfer(command, _cmd_argument)) {
                return;
            }
            break;
        case 55:
            _app_cmd_pending = true;
            _prepareShortResponse(0x20U);
            _completeCommand(kEventDone, 0, 0);
            return;
        default:
            break;
    }

    (void)response_type;
    _prepareShortResponse(0);
    _completeCommandError(kEventDone | kEventTimeout,
                          transfer == kTransferNone ? 0 : static_cast<uint8_t>(kEventDone | kEventTimeout),
                          0);
}