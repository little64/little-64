#include "device.hpp"
#include "machine_config.hpp"
#include "serial_device.hpp"
#include "cpu.hpp"
#include "support/test_harness.hpp"

#include <cstdio>
#include <string>
#include <unistd.h>
#include <vector>

template <typename Fn>
static std::string capture_stderr(Fn&& fn) {
    std::fflush(stderr);

    FILE* temp = std::tmpfile();
    if (!temp) {
        return {};
    }

    const int stderr_fd = ::fileno(stderr);
    const int saved_stderr_fd = ::dup(stderr_fd);
    if (saved_stderr_fd < 0) {
        std::fclose(temp);
        return {};
    }

    if (::dup2(::fileno(temp), stderr_fd) < 0) {
        ::close(saved_stderr_fd);
        std::fclose(temp);
        return {};
    }

    fn();

    std::fflush(stderr);
    std::rewind(temp);

    std::string output;
    char buffer[256];
    while (true) {
        const size_t count = std::fread(buffer, 1, sizeof(buffer), temp);
        if (count == 0) {
            break;
        }
        output.append(buffer, count);
    }

    ::dup2(saved_stderr_fd, stderr_fd);
    ::close(saved_stderr_fd);
    std::fclose(temp);
    return output;
}

static void test_machine_config_registration() {
    MemoryBus bus;
    std::vector<Device*> devices;

    MachineConfig cfg;
    cfg.addRam(0x1000, 0x200, "RAM")
       .addSerial(0x2000, "SERIAL");
    cfg.applyTo(bus, devices);

    CHECK_EQ(bus.regions().size(), 2ULL, "MachineConfig adds all regions");
    CHECK_EQ(devices.size(), 1ULL, "MachineConfig collects device regions");

    bus.write8(0x1000, 0xAA);
    CHECK_EQ(bus.read8(0x1000), 0xAA, "RAM region is writable");
}

static void test_serial_register_behavior_and_reset() {
    SerialDevice serial(0x3000, "SERIAL");

    serial.write8(0x3000, 'H');
    serial.write8(0x3000, 'i');
    CHECK_EQ(serial.txBuffer().size(), 2ULL, "THR writes append to TX buffer");

    serial.pushRxByte('Z');
    CHECK_EQ(serial.read8(0x3000 + 5) & 0x01, 0x01, "LSR DR bit set when RX has data");
    CHECK_EQ(serial.read8(0x3000), static_cast<uint8_t>('Z'), "RBR read pops RX byte");
    CHECK_EQ(serial.read8(0x3000 + 5) & 0x01, 0x00, "LSR DR bit cleared when RX empty");

    serial.write8(0x3000 + 3, 0x80); // DLAB on
    serial.write8(0x3000 + 0, 0x34); // DLL
    serial.write8(0x3000 + 1, 0x12); // DLM
    CHECK_EQ(serial.read8(0x3000 + 0), 0x34, "DLAB DLL write/read works");
    CHECK_EQ(serial.read8(0x3000 + 1), 0x12, "DLAB DLM write/read works");

    serial.reset();
    CHECK_EQ(serial.txBuffer().empty(), true, "reset clears TX buffer");
    CHECK_EQ(serial.read8(0x3000 + 3), 0x00, "reset clears LCR");
    CHECK_EQ(serial.read8(0x3000 + 0), 0x00, "reset clears DLL/RBR state");
    CHECK_EQ(serial.read8(0x3000 + 1), 0x00, "reset clears DLM/IER state");
}

static void test_cpu_reset_resets_devices() {
    Little64CPU cpu;

    cpu.loadProgram(std::vector<uint16_t>{0xDF00}); // STOP
    SerialDevice* serial = cpu.getSerial();
    CHECK_EQ(serial != nullptr, true, "CPU configured serial device");
    if (!serial) return;

    constexpr uint64_t SERIAL_BASE = 0x08000000ULL;
    cpu.getMemoryBus().write8(SERIAL_BASE, 'A');
    CHECK_EQ(serial->txBuffer().size(), 1ULL, "serial writes reach TX buffer before reset");

    cpu.reset();
    CHECK_EQ(serial->txBuffer().empty(), true, "CPU reset propagates to devices");
}

static void test_serial_rx_interrupt_line() {
    Little64CPU cpu;
    cpu.loadProgram(std::vector<uint16_t>{0xDF00}); // STOP

    constexpr uint64_t SERIAL_BASE = 0x08000000ULL;
    constexpr uint64_t SERIAL_IER = SERIAL_BASE + 1;
    constexpr uint64_t SERIAL_RBR = SERIAL_BASE + 0;
    constexpr uint64_t SERIAL_IIR = SERIAL_BASE + 2;
    constexpr uint64_t SERIAL_IRQ_LINE = 4;

    SerialDevice* serial = cpu.getSerial();
    CHECK_EQ(serial != nullptr, true, "CPU configured serial device for IRQ test");
    if (!serial) return;

    cpu.getMemoryBus().write8(SERIAL_IER, 0x01);
    serial->pushRxByte('Q');

    CHECK_EQ((cpu.registers.interrupt_states >> SERIAL_IRQ_LINE) & 1ULL, 1ULL,
             "Serial RX with IER enabled asserts IRQ line");
    CHECK_EQ(cpu.getMemoryBus().read8(SERIAL_IIR), 0x04,
             "IIR reports RX data available interrupt");

    CHECK_EQ(cpu.getMemoryBus().read8(SERIAL_RBR), static_cast<uint8_t>('Q'),
             "Reading RBR consumes RX byte");
    CHECK_EQ((cpu.registers.interrupt_states >> SERIAL_IRQ_LINE) & 1ULL, 0ULL,
             "Serial IRQ line clears when RX FIFO empties");
}

static void test_mmio_trace_reaches_timer_device() {
    Little64CPU cpu;
    cpu.loadProgram(std::vector<uint16_t>{0xDF00}); // STOP
    cpu.setMmioTrace(true);

    constexpr uint64_t TIMER_BASE = 0x08001000ULL;
    constexpr uint64_t TIMER_CYCLE_INTERVAL = TIMER_BASE + 16;
    const std::string trace = capture_stderr([&]() {
        cpu.getMemoryBus().write64(TIMER_CYCLE_INTERVAL, 0x42ULL);
        (void)cpu.getMemoryBus().read64(TIMER_CYCLE_INTERVAL);
    });

    CHECK_TRUE(trace.find("[mmio:TIMER] W64 +0x10 = 0x0000000000000042") != std::string::npos,
               "Timer write64 is included in MMIO trace output");
    CHECK_TRUE(trace.find("[mmio:TIMER] R64 +0x10 = 0x0000000000000042") != std::string::npos,
               "Timer read64 is included in MMIO trace output");
}

static void test_mmio_trace_preserves_serial_printable_format() {
    Little64CPU cpu;
    cpu.loadProgram(std::vector<uint16_t>{0xDF00}); // STOP
    cpu.setMmioTrace(true);

    constexpr uint64_t SERIAL_BASE = 0x08000000ULL;
    const std::string trace = capture_stderr([&]() {
        cpu.getMemoryBus().write8(SERIAL_BASE, 'A');
        (void)cpu.getMemoryBus().read8(SERIAL_BASE + 5);
    });

    CHECK_TRUE(trace.find("[mmio:SERIAL] W +0x0 = 0x41 ('A')") != std::string::npos,
               "Serial THR writes retain printable-character MMIO formatting");
    CHECK_TRUE(trace.find("[mmio:SERIAL] R +0x5 = 0x60") != std::string::npos,
               "Serial reads retain byte-oriented MMIO formatting");
}

int main() {
    std::printf("=== Little-64 device framework tests ===\n");
    test_machine_config_registration();
    test_serial_register_behavior_and_reset();
    test_cpu_reset_resets_devices();
    test_serial_rx_interrupt_line();
    test_mmio_trace_reaches_timer_device();
    test_mmio_trace_preserves_serial_printable_format();
    return print_summary();
}
