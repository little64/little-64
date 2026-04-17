#include "lite_uart_device.hpp"

#include <cstdio>

LiteUartDevice::LiteUartDevice(uint64_t base, std::string_view name, uint64_t irq_line)
    : Device(base, kSize), _name(name) {
    setInterruptLine(static_cast<int>(irq_line));
    reset();
}

void LiteUartDevice::reset() {
    _tx_buffer.clear();
    _rx_buffer.clear();
    _event_enable = 0;
    clearInterruptLine();
}

void LiteUartDevice::tick() {
}

uint8_t LiteUartDevice::rawEventStatus() const {
    uint8_t status = kEventTx;
    if (!_rx_buffer.empty()) {
        status |= kEventRx;
    }
    return status;
}

uint8_t LiteUartDevice::pendingEvents() const {
    return static_cast<uint8_t>(rawEventStatus() & _event_enable);
}

void LiteUartDevice::updateInterruptState() {
    if (pendingEvents() != 0) {
        assertInterruptLine();
    } else {
        clearInterruptLine();
    }
}

void LiteUartDevice::pushRxByte(uint8_t byte) {
    _rx_buffer.push_back(byte);
    updateInterruptState();
}

void LiteUartDevice::traceMmioRead(uint64_t addr, size_t width, uint64_t value) const {
    if (!isMmioTraceEnabled()) {
        return;
    }

    const uint64_t offset = addr - base();
    if (width == 1) {
        std::fprintf(stderr,
                     "[mmio:%.*s] R +0x%llx = 0x%02llx\n",
                     static_cast<int>(_name.size()),
                     _name.data(),
                     static_cast<unsigned long long>(offset),
                     static_cast<unsigned long long>(value & 0xFFULL));
        return;
    }

    Device::traceMmioRead(addr, width, value);
}

void LiteUartDevice::traceMmioWrite(uint64_t addr, size_t width, uint64_t value) const {
    if (!isMmioTraceEnabled()) {
        return;
    }

    const uint64_t offset = addr - base();
    if (width == 1) {
        const uint8_t byte_value = static_cast<uint8_t>(value & 0xFFULL);
        if (offset == kRxTxOffset && byte_value >= 0x20 && byte_value < 0x7F) {
            std::fprintf(stderr,
                         "[mmio:%.*s] W +0x0 = 0x%02x ('%c')\n",
                         static_cast<int>(_name.size()),
                         _name.data(),
                         byte_value,
                         byte_value);
        } else {
            std::fprintf(stderr,
                         "[mmio:%.*s] W +0x%llx = 0x%02x\n",
                         static_cast<int>(_name.size()),
                         _name.data(),
                         static_cast<unsigned long long>(offset),
                         byte_value);
        }
        return;
    }

    Device::traceMmioWrite(addr, width, value);
}

uint8_t LiteUartDevice::read8(uint64_t addr) {
    const uint64_t offset = addr - _base;
    switch (offset) {
        case kRxTxOffset: {
            uint8_t result = 0;
            if (!_rx_buffer.empty()) {
                result = _rx_buffer.front();
                _rx_buffer.pop_front();
                updateInterruptState();
            }
            return result;
        }
        case kTxFullOffset:
            return 0;
        case kRxEmptyOffset:
            return _rx_buffer.empty() ? 1 : 0;
        case kEventStatusOffset:
            return rawEventStatus();
        case kEventPendingOffset:
            return pendingEvents();
        case kEventEnableOffset:
            return _event_enable;
        default:
            return 0;
    }
}

void LiteUartDevice::write8(uint64_t addr, uint8_t val) {
    const uint64_t offset = addr - _base;
    switch (offset) {
        case kRxTxOffset:
            _tx_buffer += static_cast<char>(val);
            updateInterruptState();
            return;
        case kEventPendingOffset:
            updateInterruptState();
            return;
        case kEventEnableOffset:
            _event_enable = static_cast<uint8_t>(val & (kEventTx | kEventRx));
            updateInterruptState();
            return;
        default:
            return;
    }
}