#include "device.hpp"
#include "machine_config.hpp"
#include "serial_device.hpp"
#include "cpu.hpp"

#include <cstdio>
#include <vector>

static int _pass = 0;
static int _fail = 0;

#define CHECK_EQ(actual, expected, msg)                                         \
    do {                                                                        \
        auto _a = (actual);                                                     \
        auto _e = (expected);                                                   \
        if (_a == _e) {                                                         \
            _pass++;                                                            \
        } else {                                                                \
            std::fprintf(stderr, "FAIL [%s:%d] %s\n", __FILE__, __LINE__, (msg)); \
            _fail++;                                                            \
        }                                                                       \
    } while (0)

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

    constexpr uint64_t SERIAL_BASE = 0xFFFFFFFFFFFF0000ULL;
    cpu.getMemoryBus().write8(SERIAL_BASE, 'A');
    CHECK_EQ(serial->txBuffer().size(), 1ULL, "serial writes reach TX buffer before reset");

    cpu.reset();
    CHECK_EQ(serial->txBuffer().empty(), true, "CPU reset propagates to devices");
}

int main() {
    std::printf("=== Little-64 device framework tests ===\n");
    test_machine_config_registration();
    test_serial_register_behavior_and_reset();
    test_cpu_reset_resets_devices();

    std::printf("\n=== Results: %d passed, %d failed ===\n", _pass, _fail);
    return _fail == 0 ? 0 : 1;
}
