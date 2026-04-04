#pragma once

#include <chrono>
#include <cstdint>

/**
 * EmulatorClock provides a unified virtual-time abstraction for the emulator.
 *
 * It tracks emulated elapsed time that:
 * - Advances in sync with wall clock × speed ratio when running normally
 * - Does not advance when paused
 * - Advances by exactly 1/assumed_hz per step when single-stepping
 *
 * This allows devices like the timer to work correctly in all execution modes.
 */
class EmulatorClock {
public:
    EmulatorClock() = default;

    /**
     * Call once per CPU cycle when running normally.
     * Updates virtual time based on wall clock elapsed time scaled by speed ratio.
     */
    void tick();

    /**
     * Call once per CPU cycle during single-step mode.
     * Advances virtual time deterministically by 1/assumed_hz nanoseconds.
     */
    void tickStep();

    /**
     * Pause the clock (pause execution).
     * Snapshots wall clock and accumulates virtual nanoseconds.
     */
    void pause();

    /**
     * Resume the clock (resume execution).
     * Resets wall clock reference point for real-time tracking.
     */
    void resume();

    /**
     * Set the speed ratio for real-time execution.
     * 1.0 = real time, 0.5 = half speed, 2.0 = double speed, etc.
     */
    void setSpeedRatio(double ratio);

    /**
     * Set the assumed CPU frequency (in Hz).
     * Used to calculate deterministic virtual time advancement per step.
     * Default: 1 GHz (1e9 Hz).
     */
    void setAssumedHz(uint64_t hz);

    /**
     * Get the total virtual nanoseconds elapsed, excluding paused time.
     * Takes into account speed ratio during normal execution,
     * or deterministic step advancement during single-step.
     */
    uint64_t virtualNanoseconds() const;

    /**
     * Get the total cycle count since creation or last reset.
     */
    uint64_t cycles() const;

private:
    std::chrono::steady_clock::time_point _run_start;
    uint64_t _accumulated_ns = 0;       // virtual nanoseconds accumulated so far
    bool _paused = true;                // true when paused, false when running
    double _speed_ratio = 1.0;          // 1.0 = real time
    uint64_t _step_ns = 0;              // virtual nanoseconds advanced in current step (for single-step mode)
    bool _is_stepping = false;          // true when in single-step mode
    uint64_t _cycles = 0;               // total cycle count
    uint64_t _assumed_hz = 1'000'000'000;  // 1 GHz default
};
