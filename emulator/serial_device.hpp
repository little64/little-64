#pragma once

#include "memory_region.hpp"
#include <deque>
#include <string>

// 16550A-compatible UART MMIO device.
// 8-byte register file at [base, base+7].
//
// Register map (offsets from base):
//   +0  DLAB=0  RBR (read: pop RX FIFO or 0x00) / THR (write: push to TX buffer)
//   +0  DLAB=1  DLL (divisor latch LSB, stored but not used for timing)
//   +1  DLAB=0  IER (interrupt enable, stored but not acted upon)
//   +1  DLAB=1  DLM (divisor latch MSB)
//   +2          IIR (read: 0x01 = no interrupt pending) / FCR (write: ignored)
//   +3          LCR (bit7 = DLAB)
//   +4          MCR (modem control, stored)
//   +5          LSR (bit0=DR, bit5=THRE always 1, bit6=TEMT always 1)
//   +6          MSR (0xB0: CTS/DSR/DCD asserted)
//   +7          SCR (scratch register, r/w)
class SerialDevice : public MemoryRegion {
public:
    explicit SerialDevice(uint64_t base, std::string_view name = "SERIAL");

    uint8_t read8(uint64_t addr) override;
    void    write8(uint64_t addr, uint8_t val) override;

    std::string_view name() const override { return _name; }

    const std::string& txBuffer() const { return _tx_buffer; }
    void clearTxBuffer() { _tx_buffer.clear(); }
    void pushRxByte(uint8_t byte) { _rx_buffer.push_back(byte); }

private:
    std::string         _name;
    std::string         _tx_buffer;
    std::deque<uint8_t> _rx_buffer;

    // 16550A register state
    uint8_t _ier = 0x00;  // Interrupt Enable Register
    uint8_t _lcr = 0x00;  // Line Control Register (bit7 = DLAB)
    uint8_t _mcr = 0x00;  // Modem Control Register
    uint8_t _scr = 0x00;  // Scratch Register
    uint8_t _dll = 0x00;  // Divisor Latch LSB
    uint8_t _dlm = 0x00;  // Divisor Latch MSB
};
