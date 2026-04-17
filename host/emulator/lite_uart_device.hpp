#pragma once

#include "device.hpp"
#include "interrupt_vectors.hpp"

#include <deque>
#include <string>

class LiteUartDevice : public Device {
public:
    static constexpr uint64_t kSize = 0x100;

    static constexpr uint64_t kRxTxOffset = 0x00;
    static constexpr uint64_t kTxFullOffset = 0x04;
    static constexpr uint64_t kRxEmptyOffset = 0x08;
    static constexpr uint64_t kEventStatusOffset = 0x0C;
    static constexpr uint64_t kEventPendingOffset = 0x10;
    static constexpr uint64_t kEventEnableOffset = 0x14;

    static constexpr uint8_t kEventTx = 1u << 0;
    static constexpr uint8_t kEventRx = 1u << 1;

    explicit LiteUartDevice(uint64_t base,
                            std::string_view name = "LITEUART",
                            uint64_t irq_line = Little64Vectors::kSerialIrqVector);

    uint8_t read8(uint64_t addr) override;
    void write8(uint64_t addr, uint8_t val) override;

    void reset() override;
    void tick() override;

    std::string_view name() const override { return _name; }

    const std::string& txBuffer() const { return _tx_buffer; }
    void clearTxBuffer() { _tx_buffer.clear(); }
    void pushRxByte(uint8_t byte);

    void traceMmioRead(uint64_t addr, size_t width, uint64_t value) const override;
    void traceMmioWrite(uint64_t addr, size_t width, uint64_t value) const override;

private:
    uint8_t rawEventStatus() const;
    uint8_t pendingEvents() const;
    void updateInterruptState();

    std::string _name;
    std::string _tx_buffer;
    std::deque<uint8_t> _rx_buffer;
    uint8_t _event_enable = 0;
};