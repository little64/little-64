#include "device.hpp"
#include "machine_config.hpp"
#include "pv_block_device.hpp"
#include "serial_device.hpp"
#include "cpu.hpp"
#include "support/test_harness.hpp"

#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <string>
#include <unistd.h>
#include <utility>
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

struct TempDiskImage {
    std::string path;

    TempDiskImage() = default;
    TempDiskImage(const TempDiskImage&) = delete;
    TempDiskImage& operator=(const TempDiskImage&) = delete;
    TempDiskImage(TempDiskImage&& other) noexcept : path(std::move(other.path)) {
        other.path.clear();
    }
    TempDiskImage& operator=(TempDiskImage&& other) noexcept {
        if (this != &other) {
            if (!path.empty()) {
                ::unlink(path.c_str());
            }
            path = std::move(other.path);
            other.path.clear();
        }
        return *this;
    }

    ~TempDiskImage() {
        if (!path.empty()) {
            ::unlink(path.c_str());
        }
    }
};

static TempDiskImage create_temp_disk_image(const std::vector<uint8_t>& bytes) {
    char path_template[] = "/tmp/little64-pvblk-XXXXXX";
    const int fd = ::mkstemp(path_template);
    if (fd < 0) {
        return {};
    }

    size_t total_written = 0;
    while (total_written < bytes.size()) {
        const ssize_t rc = ::write(fd, bytes.data() + total_written, bytes.size() - total_written);
        if (rc < 0 && errno == EINTR) {
            continue;
        }
        if (rc <= 0) {
            ::close(fd);
            ::unlink(path_template);
            return {};
        }
        total_written += static_cast<size_t>(rc);
    }

    ::close(fd);
    TempDiskImage image;
    image.path = path_template;
    return image;
}

class TestInterruptSink final : public InterruptSink {
public:
    void assertInterrupt(uint64_t num) override {
        asserted = true;
        last_asserted = num;
    }

    void clearInterrupt(uint64_t num) override {
        asserted = false;
        last_cleared = num;
    }

    bool asserted = false;
    uint64_t last_asserted = 0;
    uint64_t last_cleared = 0;
};

static void test_pvblk_request_path() {
    std::vector<uint8_t> disk_bytes(static_cast<size_t>(DiskImage::kSectorSize * 2), 0);
    const char payload[] = "pvblk-ok";
    std::memcpy(disk_bytes.data() + DiskImage::kSectorSize, payload, sizeof(payload) - 1);

    TempDiskImage disk = create_temp_disk_image(disk_bytes);
    CHECK_TRUE(!disk.path.empty(), "temp pvblk disk image created");
    if (disk.path.empty()) {
        return;
    }

    MemoryBus bus;
    std::vector<Device*> devices;
    TestInterruptSink irq_sink;

    constexpr uint64_t ram_base = 0x1000;
    constexpr uint64_t pvblk_base = 0x3000;
    constexpr uint64_t request_addr = ram_base + 0x100;
    constexpr uint64_t buffer_addr = ram_base + 0x200;

    MachineConfig cfg;
    cfg.addRam(ram_base, 0x1000, "RAM")
       .addPvBlock(pvblk_base, disk.path, false, "PVBLK");
    cfg.applyTo(bus, devices, &irq_sink);

    CHECK_EQ(devices.size(), 1ULL, "MachineConfig collects PVBLK device");
    CHECK_EQ(bus.read64(pvblk_base + static_cast<uint64_t>(PvBlockDevice::RegisterOffset::Magic)),
             PvBlockDevice::kMagic,
             "PVBLK exposes expected magic register");
    CHECK_EQ(bus.read64(pvblk_base + static_cast<uint64_t>(PvBlockDevice::RegisterOffset::SectorCount)),
             2ULL,
             "PVBLK exposes disk sector count");

    for (size_t i = 0; i < DiskImage::kSectorSize; ++i) {
        bus.write8(buffer_addr + i, 0x00);
    }

    bus.write64(request_addr + offsetof(PvBlockDevice::RequestHeader, op), PvBlockDevice::kRequestRead);
    bus.write64(request_addr + offsetof(PvBlockDevice::RequestHeader, status), 0xFFFFFFFFFFFFFFFFULL);
    bus.write64(request_addr + offsetof(PvBlockDevice::RequestHeader, sector), 1);
    bus.write64(request_addr + offsetof(PvBlockDevice::RequestHeader, sector_count), 1);
    bus.write64(request_addr + offsetof(PvBlockDevice::RequestHeader, buffer_phys), buffer_addr);
    bus.write64(request_addr + offsetof(PvBlockDevice::RequestHeader, buffer_len), DiskImage::kSectorSize);
    bus.write64(request_addr + offsetof(PvBlockDevice::RequestHeader, reserved0), 0);
    bus.write64(request_addr + offsetof(PvBlockDevice::RequestHeader, reserved1), 0);

    bus.write64(pvblk_base + static_cast<uint64_t>(PvBlockDevice::RegisterOffset::RequestAddress), request_addr);
    bus.write64(pvblk_base + static_cast<uint64_t>(PvBlockDevice::RegisterOffset::Kick), 1);

    CHECK_EQ(bus.read64(request_addr + offsetof(PvBlockDevice::RequestHeader, status)),
             PvBlockDevice::kRequestStatusOk,
             "PVBLK request completion status is written back to guest memory");
    CHECK_TRUE(irq_sink.asserted, "PVBLK read completion asserts its interrupt line");
    CHECK_EQ(irq_sink.last_asserted, Little64Vectors::kPvBlockIrqVector,
             "PVBLK uses the high-range IRQ vector");
    CHECK_EQ(bus.read64(pvblk_base + static_cast<uint64_t>(PvBlockDevice::RegisterOffset::Status)) &
                 PvBlockDevice::kStatusInterruptPending,
             PvBlockDevice::kStatusInterruptPending,
             "PVBLK status reports pending completion interrupt");

    CHECK_EQ(bus.read8(buffer_addr + 0), static_cast<uint8_t>('p'), "PVBLK transfers sector data into guest RAM");
    CHECK_EQ(bus.read8(buffer_addr + 7), static_cast<uint8_t>('k'), "PVBLK preserves guest buffer contents");

    bus.write64(pvblk_base + static_cast<uint64_t>(PvBlockDevice::RegisterOffset::InterruptAck), 1);
    CHECK_FALSE(irq_sink.asserted, "PVBLK interrupt ack clears the interrupt line");
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
    constexpr uint64_t SERIAL_IRQ_LINE = Little64Vectors::kSerialIrqVector;
    constexpr uint64_t SERIAL_IRQ_BIT = Little64Vectors::interruptBitForVector(SERIAL_IRQ_LINE);

    SerialDevice* serial = cpu.getSerial();
    CHECK_EQ(serial != nullptr, true, "CPU configured serial device for IRQ test");
    if (!serial) return;

    cpu.getMemoryBus().write8(SERIAL_IER, 0x01);
    serial->pushRxByte('Q');

    CHECK_EQ(cpu.registers.interrupt_states_high & SERIAL_IRQ_BIT, SERIAL_IRQ_BIT,
             "Serial RX with IER enabled asserts the high-bank IRQ bit");
    CHECK_EQ(cpu.getMemoryBus().read8(SERIAL_IIR), 0x04,
             "IIR reports RX data available interrupt");

    CHECK_EQ(cpu.getMemoryBus().read8(SERIAL_RBR), static_cast<uint8_t>('Q'),
             "Reading RBR consumes RX byte");
    CHECK_EQ(cpu.registers.interrupt_states_high & SERIAL_IRQ_BIT, 0ULL,
             "Serial IRQ line clears when RX FIFO empties");
}

static void test_serial_tx_interrupt_line() {
    Little64CPU cpu;
    cpu.loadProgram(std::vector<uint16_t>{0xDF00}); // STOP

    constexpr uint64_t SERIAL_BASE = 0x08000000ULL;
    constexpr uint64_t SERIAL_IER = SERIAL_BASE + 1;
    constexpr uint64_t SERIAL_RBR = SERIAL_BASE + 0;
    constexpr uint64_t SERIAL_IIR = SERIAL_BASE + 2;
    constexpr uint64_t SERIAL_IRQ_LINE = Little64Vectors::kSerialIrqVector;
    constexpr uint64_t SERIAL_IRQ_BIT = Little64Vectors::interruptBitForVector(SERIAL_IRQ_LINE);

    SerialDevice* serial = cpu.getSerial();
    CHECK_EQ(serial != nullptr, true, "CPU configured serial device for TX IRQ test");
    if (!serial) return;

    cpu.getMemoryBus().write8(SERIAL_IER, 0x02);

    CHECK_EQ(cpu.registers.interrupt_states_high & SERIAL_IRQ_BIT, SERIAL_IRQ_BIT,
             "Serial THRE with IER enabled asserts the high-bank IRQ bit");
    CHECK_EQ(cpu.getMemoryBus().read8(SERIAL_IIR), 0x02,
             "IIR reports THRE interrupt when TX-empty IRQ is enabled");

    cpu.getMemoryBus().write8(SERIAL_BASE, 'A');
    CHECK_EQ(cpu.registers.interrupt_states_high & SERIAL_IRQ_BIT, SERIAL_IRQ_BIT,
             "Serial THRE IRQ remains pending after immediate TX completion");

    cpu.getMemoryBus().write8(SERIAL_IER, 0x03);
    serial->pushRxByte('Q');
    CHECK_EQ(cpu.getMemoryBus().read8(SERIAL_IIR), 0x04,
             "IIR prioritizes RX data available over THRE when both are pending");
    CHECK_EQ(cpu.getMemoryBus().read8(SERIAL_RBR), static_cast<uint8_t>('Q'),
             "Reading RBR still consumes RX data with THRE enabled");
    CHECK_EQ(cpu.getMemoryBus().read8(SERIAL_IIR), 0x02,
             "IIR falls back to THRE after RX data is consumed");

    cpu.getMemoryBus().write8(SERIAL_IER, 0x00);
    CHECK_EQ(cpu.registers.interrupt_states_high & SERIAL_IRQ_BIT, 0ULL,
             "Disabling serial interrupts clears the THRE IRQ line");
}

static void test_masked_irq_waits_until_reenabled() {
    Little64CPU cpu;
    constexpr uint16_t MOVE_R0_TO_R0 = 0x1000;
    constexpr uint16_t STOP = 0xDF00;
    cpu.loadProgram(std::vector<uint16_t>{MOVE_R0_TO_R0, MOVE_R0_TO_R0});

    constexpr uint64_t IRQ_LINE = Little64Vectors::kSerialIrqVector;
    constexpr uint64_t VECTOR_BASE = 0x200;
    constexpr uint64_t HANDLER_ADDR = 0x300;
    constexpr uint64_t IRQ_BIT = Little64Vectors::interruptBitForVector(IRQ_LINE);

    cpu.getMemoryBus().write64(VECTOR_BASE + (IRQ_LINE * 8), HANDLER_ADDR);
    cpu.getMemoryBus().write16(HANDLER_ADDR, STOP);

    cpu.registers.interrupt_table_base = VECTOR_BASE;
    cpu.registers.interrupt_mask_high = IRQ_BIT;
    cpu.registers.setInterruptEnabled(false);
    cpu.assertInterrupt(IRQ_LINE);

    cpu.cycle();

    CHECK_TRUE(cpu.isRunning, "CPU keeps running when a hardware IRQ arrives with IRQs disabled");
    CHECK_EQ(cpu.registers.regs[15], 0x2ULL,
             "Pending IRQ does not vector while IRQs are disabled");
    CHECK_FALSE(cpu.registers.isInInterrupt(),
                "CPU does not enter interrupt context while IRQs are disabled");
    CHECK_EQ(cpu.registers.interrupt_states_high & IRQ_BIT, IRQ_BIT,
             "Pending IRQ remains latched in the high IRQ bank while IRQs are disabled");

    cpu.registers.setInterruptEnabled(true);
    cpu.cycle();

    CHECK_TRUE(cpu.registers.isInInterrupt(),
               "Pending IRQ vectors once IRQs are re-enabled");
    CHECK_EQ(cpu.registers.getCurrentInterruptNumber(), IRQ_LINE,
             "Interrupt delivery preserves the latched IRQ number");
    CHECK_EQ(cpu.registers.regs[15], HANDLER_ADDR,
             "CPU jumps to the interrupt handler after IRQs are re-enabled");
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
    test_pvblk_request_path();
    test_serial_register_behavior_and_reset();
    test_cpu_reset_resets_devices();
    test_serial_rx_interrupt_line();
    test_serial_tx_interrupt_line();
    test_masked_irq_waits_until_reenabled();
    test_mmio_trace_reaches_timer_device();
    test_mmio_trace_preserves_serial_printable_format();
    return print_summary();
}
