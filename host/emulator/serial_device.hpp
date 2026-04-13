#pragma once

#include "device.hpp"
#include "interrupt_vectors.hpp"
#include <deque>
#include <string>

// 16550A-compatible UART MMIO device.
// 8-byte register file at [base, base+7].
//
// Register map (offsets from base):
//   +0  DLAB=0  RBR (read: pop RX FIFO or 0x00) / THR (write: push to TX buffer)
//   +0  DLAB=1  DLL (divisor latch LSB, stored but not used for timing)
//   +1  DLAB=0  IER (bit0=RX ready irq enable, bit1=THRE irq enable)
//   +1  DLAB=1  DLM (divisor latch MSB)
//   +2          IIR (read: 0x04 = RX ready, 0x02 = THRE, 0x01 = no irq) / FCR (write: ignored)
//   +3          LCR (bit7 = DLAB)
//   +4          MCR (modem control, stored)
//   +5          LSR (bit0=DR, bit5=THRE always 1, bit6=TEMT always 1)
//   +6          MSR (0xB0: CTS/DSR/DCD asserted)
//   +7          SCR (scratch register, r/w)
class SerialDevice : public Device {
public:
    explicit SerialDevice(uint64_t base, std::string_view name = "SERIAL",
                          uint64_t irq_line = Little64Vectors::kSerialIrqVector);

    uint8_t read8(uint64_t addr) override;
    void    write8(uint64_t addr, uint8_t val) override;

    void reset() override;
    void tick() override;

    std::string_view name() const override { return _name; }

    const std::string& txBuffer() const { return _tx_buffer; }
    void clearTxBuffer() { _tx_buffer.clear(); }
    void pushRxByte(uint8_t byte);

    void traceMmioRead(uint64_t addr, size_t width, uint64_t value) const override;
    void traceMmioWrite(uint64_t addr, size_t width, uint64_t value) const override;

private:
    void updateInterruptState();

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
