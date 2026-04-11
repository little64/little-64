#pragma once

#include "memory_region.hpp"

#include <cstdio>

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

    virtual void setMmioTrace(bool enabled) {
        _trace_mmio = enabled;
        setNotifyAccess(enabled);
    }

    virtual void traceMmioRead(uint64_t addr, size_t width, uint64_t value) const {
        traceMmioAccess("R", addr, width, value);
    }

    virtual void traceMmioWrite(uint64_t addr, size_t width, uint64_t value) const {
        traceMmioAccess("W", addr, width, value);
    }

    // MemoryRegion notification hooks — forward to MMIO trace.
    void notifyRead(uint64_t addr, size_t width, uint64_t value) const override {
        traceMmioRead(addr, width, value);
    }
    void notifyWrite(uint64_t addr, size_t width, uint64_t value) const override {
        traceMmioWrite(addr, width, value);
    }

    void connectInterruptSink(InterruptSink* sink) { _interrupt_sink = sink; }
    void setInterruptLine(int line) { _interrupt_line = line; }

protected:
    bool isMmioTraceEnabled() const { return _trace_mmio; }

    void traceMmioAccess(const char* op, uint64_t addr, size_t width, uint64_t value) const {
        if (!_trace_mmio) {
            return;
        }

        const std::string_view region_name = name();
        const uint64_t offset = addr - _base;
        const unsigned width_bits = static_cast<unsigned>(width * 8);
        const int value_digits = static_cast<int>(width * 2);
        std::fprintf(stderr,
                     "[mmio:%.*s] %s%u +0x%llx = 0x%0*llx\n",
                     static_cast<int>(region_name.size()),
                     region_name.data(),
                     op,
                     width_bits,
                     static_cast<unsigned long long>(offset),
                     value_digits,
                     static_cast<unsigned long long>(value));
    }

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
    bool _trace_mmio = false;
};
