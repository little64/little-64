#include "timer_device.hpp"

TimerDevice::TimerDevice(uint64_t base)
    : Device(base, 32), _clock(nullptr) {
    setInterruptLine(5);  // IRQ 5
    reset();
}

void TimerDevice::reset() {
    _cycle_interval = 0;
    _time_interval_ns = 0;
    _next_cycle_fire = 0;
    _next_time_fire_ns = 0;
    _fired_this_cycle = false;
}

void TimerDevice::tick() {
    if (!_clock) {
        return;  // Not properly initialized
    }

    uint64_t c = _clock->cycles();
    uint64_t t = _clock->virtualNanoseconds();

    bool should_fire = false;

    // Check cycle-based interval
    if (_cycle_interval != 0 && c >= _next_cycle_fire) {
        _next_cycle_fire = c + _cycle_interval;
        should_fire = true;
    }

    // Check time-based interval
    if (_time_interval_ns != 0 && t >= _next_time_fire_ns) {
        _next_time_fire_ns = t + _time_interval_ns;
        should_fire = true;
    }

    if (should_fire && !_fired_this_cycle) {
        _fired_this_cycle = true;
        assertInterruptLine();
    } else if (!should_fire) {
        _fired_this_cycle = false;
    }
}

uint64_t TimerDevice::read64(uint64_t addr) {
    if (!_clock) {
        return 0;
    }

    uint64_t offset = addr - base();
    if (offset > 32 || (offset & 0x7) != 0) {
        return 0;  // Out of bounds or misaligned
    }

    switch (offset) {
        case 0:
            // Cycle counter (read-only)
            return _clock->cycles();

        case 8:
            // Virtual nanoseconds (read-only)
            return _clock->virtualNanoseconds();

        case 16:
            // Cycle interval
            return _cycle_interval;

        case 24:
            // Time interval
            return _time_interval_ns;

        default:
            return 0;
    }
}

void TimerDevice::write64(uint64_t addr, uint64_t val) {
    if (!_clock) {
        return;
    }

    uint64_t offset = addr - base();
    if (offset > 32 || (offset & 0x7) != 0) {
        return;  // Out of bounds or misaligned
    }

    switch (offset) {
        case 0:
        case 8:
            // Read-only registers (cycle counter, virtual nanoseconds)
            return;

        case 16:
            // Cycle interval
            _cycle_interval = val;
            if (val != 0) {
                _next_cycle_fire = _clock->cycles() + val;
                _fired_this_cycle = false;
            } else {
                clearInterruptLine();
            }
            break;

        case 24:
            // Time interval
            _time_interval_ns = val;
            if (val != 0) {
                _next_time_fire_ns = _clock->virtualNanoseconds() + val;
                _fired_this_cycle = false;
            } else {
                clearInterruptLine();
            }
            break;

        default:
            break;
    }
}

// Dummy implementations required by MemoryRegion interface
uint8_t TimerDevice::read8(uint64_t addr) {
    return (read64(addr & ~0x7ULL) >> ((addr & 0x7) * 8)) & 0xFF;
}

void TimerDevice::write8(uint64_t addr, uint8_t val) {
    // For now, ignore byte-level writes; the timer expects 64-bit accesses
}
