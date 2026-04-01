#include "serial_device.hpp"

SerialDevice::SerialDevice(uint64_t base, std::string_view name)
    : Device(base, 8), _name(name) {}

void SerialDevice::reset() {
    _tx_buffer.clear();
    _rx_buffer.clear();
    _ier = 0x00;
    _lcr = 0x00;
    _mcr = 0x00;
    _scr = 0x00;
    _dll = 0x00;
    _dlm = 0x00;
}

void SerialDevice::tick() {
}

uint8_t SerialDevice::read8(uint64_t addr) {
    bool dlab = (_lcr & 0x80) != 0;
    switch (addr - _base) {
        case 0:
            if (dlab) return _dll;
            if (!_rx_buffer.empty()) {
                uint8_t byte = _rx_buffer.front();
                _rx_buffer.pop_front();
                return byte;
            }
            return 0x00;
        case 1:
            if (dlab) return _dlm;
            return _ier;
        case 2:
            return 0x01;  // IIR: no interrupt pending
        case 3:
            return _lcr;
        case 4:
            return _mcr;
        case 5: {
            // LSR: bit0=DR (data ready), bit5=THRE (TX empty), bit6=TEMT (TX idle)
            uint8_t lsr = 0x60;  // THRE + TEMT always set
            if (!_rx_buffer.empty()) lsr |= 0x01;
            return lsr;
        }
        case 6:
            return 0xB0;  // MSR: CTS, DSR, DCD asserted
        case 7:
            return _scr;
        default:
            return 0xFF;
    }
}

void SerialDevice::write8(uint64_t addr, uint8_t val) {
    bool dlab = (_lcr & 0x80) != 0;
    switch (addr - _base) {
        case 0:
            if (dlab) { _dll = val; return; }
            _tx_buffer += static_cast<char>(val);
            return;
        case 1:
            if (dlab) { _dlm = val; return; }
            _ier = val;
            return;
        case 2:
            return;  // FCR: accepted, ignored
        case 3:
            _lcr = val;
            return;
        case 4:
            _mcr = val;
            return;
        case 5:
        case 6:
            return;  // LSR/MSR read-only
        case 7:
            _scr = val;
            return;
        default:
            return;
    }
}
