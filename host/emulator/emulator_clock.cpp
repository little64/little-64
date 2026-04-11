#include "emulator_clock.hpp"

void EmulatorClock::tick() {
    if (_paused) {
        return;  // Don't advance when paused
    }

    if (_is_stepping) {
        // In single-step mode, tick() should not be called; tickStep() should be used instead
        // But if it is called, treat it like tickStep() for safety
        tickStep();
        return;
    }

    ++_cycles;

    // Only query wall clock every kClockSampleInterval cycles to avoid
    // per-cycle clock_gettime syscall overhead.
    if ((_cycles & kClockSampleMask) == 0) {
        auto now = std::chrono::steady_clock::now();
        auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(now - _run_start).count();
        _cached_virtual_ns = _accumulated_ns + uint64_t(elapsed * _speed_ratio);
    }
}

void EmulatorClock::tickStep() {
    if (!_is_stepping) {
        // Entering single-step mode
        _is_stepping = true;
        _step_ns = 0;
    }

    // Advance by deterministic amount per step: 1e9 / assumed_hz nanoseconds
    uint64_t ns_per_step = 1'000'000'000ULL / _assumed_hz;
    _step_ns += ns_per_step;

    ++_cycles;
}

void EmulatorClock::pause() {
    if (_paused) {
        return;  // Already paused
    }

    if (_is_stepping) {
        // Already in single-step mode, which is effectively paused
        _paused = true;
        _is_stepping = false;
        return;
    }

    // Snapshot current virtual time
    auto now = std::chrono::steady_clock::now();
    auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(now - _run_start).count();
    _accumulated_ns += uint64_t(elapsed * _speed_ratio);

    _paused = true;
}

void EmulatorClock::resume() {
    if (!_paused && !_is_stepping) {
        return;  // Already running
    }

    _paused = false;
    _is_stepping = false;
    _step_ns = 0;
    _run_start = std::chrono::steady_clock::now();
    _cached_virtual_ns = _accumulated_ns;
}

void EmulatorClock::setSpeedRatio(double ratio) {
    if (ratio <= 0.0) {
        ratio = 1.0;  // Clamp to positive
    }
    _speed_ratio = ratio;
}

void EmulatorClock::setAssumedHz(uint64_t hz) {
    if (hz == 0) {
        hz = 1'000'000'000;  // Default to 1 GHz
    }
    _assumed_hz = hz;
}

uint64_t EmulatorClock::virtualNanoseconds() const {
    if (_paused || _is_stepping) {
        return _accumulated_ns + _step_ns;
    }

    // Running: return cached value (updated every kClockSampleInterval cycles
    // in tick()) to avoid per-call clock_gettime overhead.
    return _cached_virtual_ns;
}

uint64_t EmulatorClock::cycles() const {
    return _cycles;
}
