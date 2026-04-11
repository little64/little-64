#include "serial_device.hpp"

#include <cstdio>

SerialDevice::SerialDevice(uint64_t base, std::string_view name, uint64_t irq_line)
    : Device(base, 8), _name(name) {
    setInterruptLine(static_cast<int>(irq_line));
}

void SerialDevice::reset() {
    _tx_buffer.clear();
    _rx_buffer.clear();
    _ier = 0x00;
    _lcr = 0x00;
    _mcr = 0x00;
    _scr = 0x00;
    _dll = 0x00;
    _dlm = 0x00;
    clearInterruptLine();
}

void SerialDevice::tick() {
}

void SerialDevice::updateInterruptState() {
    const bool rx_ready_irq_enabled = (_ier & 0x01) != 0;
    const bool has_rx_data = !_rx_buffer.empty();
    if (rx_ready_irq_enabled && has_rx_data) {
        assertInterruptLine();
    } else {
        clearInterruptLine();
    }
}

void SerialDevice::pushRxByte(uint8_t byte) {
    _rx_buffer.push_back(byte);
    updateInterruptState();
}

void SerialDevice::traceMmioRead(uint64_t addr, size_t width, uint64_t value) const {
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

void SerialDevice::traceMmioWrite(uint64_t addr, size_t width, uint64_t value) const {
    if (!isMmioTraceEnabled()) {
        return;
    }

    const uint64_t offset = addr - base();
    if (width == 1) {
        const uint8_t byte_value = static_cast<uint8_t>(value & 0xFFULL);
        if (offset == 0 && byte_value >= 0x20 && byte_value < 0x7F) {
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

uint8_t SerialDevice::read8(uint64_t addr) {
    bool dlab = (_lcr & 0x80) != 0;
    uint8_t offset = static_cast<uint8_t>(addr - _base);
    uint8_t result;
    switch (offset) {
        case 0:
            if (dlab) { result = _dll; break; }
            if (!_rx_buffer.empty()) {
                result = _rx_buffer.front();
                _rx_buffer.pop_front();
                updateInterruptState();
            } else {
                result = 0x00;
            }
            break;
        case 1:
            result = dlab ? _dlm : _ier;
            break;
        case 2:
            result = (((_ier & 0x01) != 0) && !_rx_buffer.empty()) ? 0x04 : 0x01;
            break;
        case 3:  result = _lcr;  break;
        case 4:  result = _mcr;  break;
        case 5: {
            // LSR: bit0=DR (data ready), bit5=THRE (TX empty), bit6=TEMT (TX idle)
            result = 0x60;  // THRE + TEMT always set
            if (!_rx_buffer.empty()) result |= 0x01;
            break;
        }
        case 6:  result = 0xB0;   break;  // MSR: CTS, DSR, DCD asserted
        case 7:  result = _scr;   break;
        default: result = 0xFF;   break;
    }
    return result;
}

void SerialDevice::write8(uint64_t addr, uint8_t val) {
    bool dlab = (_lcr & 0x80) != 0;
    uint8_t offset = static_cast<uint8_t>(addr - _base);
    switch (offset) {
        case 0:
            if (dlab) { _dll = val; return; }
            _tx_buffer += static_cast<char>(val);
            return;
        case 1:
            if (dlab) { _dlm = val; return; }
            _ier = val;
            updateInterruptState();
            return;
        case 2:   return;  // FCR: accepted, ignored
        case 3:   _lcr = val; return;
        case 4:   _mcr = val; return;
        case 5:
        case 6:   return;  // LSR/MSR read-only
        case 7:   _scr = val; return;
        default:  return;
    }
}
