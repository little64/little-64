#pragma once

#include "memory_region.hpp"

class InterruptSink {
public:
    virtual ~InterruptSink() = default;
    virtual void assertInterrupt(uint64_t num) = 0;
    virtual void clearInterrupt(uint64_t num) = 0;
};

class Device : public MemoryRegion {
public:
    Device(uint64_t base, uint64_t size) : MemoryRegion(base, size) {}
    ~Device() override = default;

    virtual void reset() {}
    virtual void tick() {}

    void connectInterruptSink(InterruptSink* sink) { _interrupt_sink = sink; }
    void setInterruptLine(int line) { _interrupt_line = line; }

protected:
    void assertInterruptLine() {
        if (_interrupt_sink && _interrupt_line >= 0) {
            _interrupt_sink->assertInterrupt(static_cast<uint64_t>(_interrupt_line));
        }
    }

    void clearInterruptLine() {
        if (_interrupt_sink && _interrupt_line >= 0) {
            _interrupt_sink->clearInterrupt(static_cast<uint64_t>(_interrupt_line));
        }
    }

private:
    InterruptSink* _interrupt_sink = nullptr;
    int _interrupt_line = -1;
};
