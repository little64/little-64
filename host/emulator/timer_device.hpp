#pragma once

#include "device.hpp"
#include "emulator_clock.hpp"
#include <cstdint>

/**
 * TimerDevice: MMIO-based timer with dual-mode interrupt firing.
 *
 * MMIO layout at base address (32 bytes):
 *   +0  (RO, 8B): cycle counter (from clock.cycles())
 *   +8  (RO, 8B): virtual nanoseconds (from clock.virtualNanoseconds())
 *   +16 (RW, 8B): cycle interval (0 = disabled)
 *   +24 (RW, 8B): time interval in ns (0 = disabled)
 *
 * Fires interrupts when either threshold is crossed.
 * IRQ line: 5 (must be wired by machine_config).
 */
class TimerDevice : public Device {
public:
    // Creates a timer device at the given MMIO base address (32 bytes).
    // The clock pointer can be set later with setClock().
    explicit TimerDevice(uint64_t base);
    ~TimerDevice() override = default;

    // Set the clock (must be called before device is used)
    void setClock(const EmulatorClock* clock) { _clock = clock; }

    // MemoryRegion interface (MMIO)
    // The timer device operates on 8-byte registers, so we override read64/write64
    uint64_t read64(uint64_t addr) override;
    void write64(uint64_t addr, uint64_t val) override;

    // Required by MemoryRegion (though not used for MMIO, just dummy implementations)
    uint8_t read8(uint64_t addr) override;
    void write8(uint64_t addr, uint8_t val) override;

    std::string_view name() const override { return "TIMER"; }

    // Device interface
    void reset() override;
    void tick() override;

private:
    const EmulatorClock* _clock;        // not owned, points to CPU's clock

    uint64_t _cycle_interval = 0;       // 0 = disabled
    uint64_t _time_interval_ns = 0;     // 0 = disabled

    uint64_t _next_cycle_fire = 0;      // when to fire next cycle-based interrupt
    uint64_t _next_time_fire_ns = 0;    // when to fire next time-based interrupt

    bool _fired_this_cycle = false;     // Prevent multiple fires per cycle
};
