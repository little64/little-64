#include "device.hpp"
#include "disk_image.hpp"
#include "lite_dram_dfii_stub_device.hpp"
#include "lite_sdcard_device.hpp"
#include "lite_uart_device.hpp"
#include "machine_config.hpp"
#include "pv_block_device.hpp"
#include "serial_device.hpp"
#include "cpu.hpp"
#include "support/test_harness.hpp"

#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <array>
#include <fcntl.h>
#include <fstream>
#include <string>
#include <sys/types.h>
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

static size_t count_occurrences(const std::string& haystack, const std::string& needle) {
    if (needle.empty()) {
        return 0;
    }

    size_t count = 0;
    size_t pos = 0;
    while ((pos = haystack.find(needle, pos)) != std::string::npos) {
        ++count;
        pos += needle.size();
    }
    return count;
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

static TempDiskImage create_temp_sparse_disk_image(uint64_t size_bytes) {
    char path_template[] = "/tmp/little64-sparse-XXXXXX";
    const int fd = ::mkstemp(path_template);
    if (fd < 0) {
        return {};
    }
    if (::ftruncate(fd, static_cast<off_t>(size_bytes)) != 0) {
        ::close(fd);
        ::unlink(path_template);
        return {};
    }

    ::close(fd);
    TempDiskImage image;
    image.path = path_template;
    return image;
}

static uint64_t current_rss_bytes() {
    std::ifstream statm("/proc/self/statm");
    uint64_t total_pages = 0;
    uint64_t resident_pages = 0;
    if (!(statm >> total_pages >> resident_pages)) {
        return 0;
    }

    const long page_size = ::sysconf(_SC_PAGESIZE);
    if (page_size <= 0) {
        return 0;
    }
    return resident_pages * static_cast<uint64_t>(page_size);
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

static void test_liteuart_register_behavior_and_irq() {
    LiteUartDevice uart(0x4000, "LITEUART");
    TestInterruptSink irq_sink;
    uart.connectInterruptSink(&irq_sink);

    uart.write8(0x4000 + LiteUartDevice::kRxTxOffset, 'H');
    uart.write8(0x4000 + LiteUartDevice::kRxTxOffset, 'i');
    CHECK_EQ(uart.txBuffer().size(), 2ULL, "LiteUART RXTX writes append to TX buffer");
    CHECK_EQ(uart.read8(0x4000 + LiteUartDevice::kTxFullOffset), 0,
             "LiteUART TX path is never full in the emulator");

    uart.write8(0x4000 + LiteUartDevice::kEventEnableOffset, LiteUartDevice::kEventRx);
    uart.pushRxByte('Z');
    CHECK_TRUE(irq_sink.asserted, "LiteUART RX data with EV_ENABLE set asserts the interrupt line");
    CHECK_EQ(irq_sink.last_asserted, Little64Vectors::kSerialIrqVector,
             "LiteUART reuses the serial IRQ vector");
    CHECK_EQ(uart.read8(0x4000 + LiteUartDevice::kRxEmptyOffset), 0,
             "LiteUART RXEMPTY clears when input is queued");
    CHECK_EQ(uart.read8(0x4000 + LiteUartDevice::kEventPendingOffset), LiteUartDevice::kEventRx,
             "LiteUART EV_PENDING reports enabled RX data");
    CHECK_EQ(uart.read8(0x4000 + LiteUartDevice::kRxTxOffset), static_cast<uint8_t>('Z'),
             "LiteUART RXTX reads consume queued input");
    CHECK_EQ(uart.read8(0x4000 + LiteUartDevice::kRxEmptyOffset), 1,
             "LiteUART RXEMPTY sets once the RX FIFO drains");
    CHECK_FALSE(irq_sink.asserted, "LiteUART clears the interrupt line once no enabled events remain");

    uart.write8(0x4000 + LiteUartDevice::kEventEnableOffset, LiteUartDevice::kEventTx);
    CHECK_TRUE(irq_sink.asserted, "LiteUART TX-ready event asserts immediately when enabled");
    CHECK_EQ(uart.read8(0x4000 + LiteUartDevice::kEventPendingOffset), LiteUartDevice::kEventTx,
             "LiteUART EV_PENDING reports TX-ready while TX IRQs are enabled");

    uart.reset();
    CHECK_TRUE(uart.txBuffer().empty(), "LiteUART reset clears buffered TX output");
    CHECK_EQ(uart.read8(0x4000 + LiteUartDevice::kEventEnableOffset), 0,
             "LiteUART reset clears EV_ENABLE");
}

static void test_litedram_dfii_stub_register_behavior() {
    LiteDramDfiiStubDevice dfi(0x6000, "LITEDRAM");

    CHECK_EQ(dfi.read32(0x6000 + LiteDramDfiiStubDevice::kControlOffset),
             LiteDramDfiiStubDevice::kControlHardwareMode,
             "LiteDRAM DFII stub starts in hardware-control mode");

    dfi.write32(0x6000 + LiteDramDfiiStubDevice::kControlOffset, 0x0E);
    dfi.write32(0x6000 + LiteDramDfiiStubDevice::kPhase0AddressOffset, 0x920);
    dfi.write32(0x6000 + LiteDramDfiiStubDevice::kPhase0BankAddressOffset, 0x2);
    dfi.write32(0x6000 + LiteDramDfiiStubDevice::kPhase0CommandOffset, 0x0F);
    dfi.write32(0x6000 + LiteDramDfiiStubDevice::kPhase0CommandIssueOffset, 1);

    CHECK_EQ(dfi.read32(0x6000 + LiteDramDfiiStubDevice::kControlOffset), 0x0E,
             "LiteDRAM DFII stub stores control-register writes");
    CHECK_EQ(dfi.read32(0x6000 + LiteDramDfiiStubDevice::kPhase0AddressOffset), 0x920,
             "LiteDRAM DFII stub stores address-register writes");
    CHECK_EQ(dfi.read32(0x6000 + LiteDramDfiiStubDevice::kPhase0BankAddressOffset), 0x2,
             "LiteDRAM DFII stub stores bank-address writes");
    CHECK_EQ(dfi.read32(0x6000 + LiteDramDfiiStubDevice::kPhase0CommandOffset), 0x0F,
             "LiteDRAM DFII stub stores phase command writes");
    CHECK_EQ(dfi.read32(0x6000 + LiteDramDfiiStubDevice::kPhase0CommandIssueOffset), 1,
             "LiteDRAM DFII stub stores command-issue pulses for functional emulation");
    CHECK_EQ(dfi.read32(0x6000 + 0x24), 0U,
             "LiteDRAM DFII stub keeps read-data windows zero-filled");

    dfi.reset();
    CHECK_EQ(dfi.read32(0x6000 + LiteDramDfiiStubDevice::kControlOffset),
             LiteDramDfiiStubDevice::kControlHardwareMode,
             "LiteDRAM DFII stub reset restores hardware-control default");
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

static void test_litex_flash_loader_configures_litex_machine() {
    Little64CPU cpu;
    const std::vector<uint8_t> flash_bytes = {0x00, 0xDF, 0x34, 0x12};
    constexpr uint64_t kExpectedFlashRamSize = 64ULL * 1024ULL * 1024ULL;

    CHECK_TRUE(cpu.loadProgramLiteXFlashImage(flash_bytes), "LiteX flash loader accepts a raw flash image");
    CHECK_EQ(cpu.registers.regs[15], 0x20000000ULL,
             "LiteX flash loader enters execution at the mapped flash base");
    CHECK_EQ(cpu.getMemoryBus().read16(0x20000000ULL), 0xDF00,
             "LiteX flash loader exposes the raw image through the flash ROM window");
    CHECK_EQ(cpu.getMemoryBus().read8(0x20000000ULL + 0x1000ULL), 0xFF,
             "LiteX flash window is padded with erased-flash bytes beyond the image payload");

    cpu.getMemoryBus().write8(0x8000, 0xA5);
    CHECK_EQ(cpu.getMemoryBus().read8(0x8000), 0xA5,
             "LiteX flash mode keeps low RAM writable for stage-0 scratch state");

    const auto& regions = cpu.getMemoryBus().regions();
    CHECK_EQ(regions.size(), 5ULL,
             "LiteX flash mode installs RAM, SRAM, flash, LiteUART, and timer regions");
    CHECK_TRUE(std::any_of(regions.begin(), regions.end(), [](const auto& region) {
                   return region->name() == "FLASH";
               }),
               "LiteX flash mode includes a named flash ROM region");
    CHECK_TRUE(std::any_of(regions.begin(), regions.end(), [](const auto& region) {
                   return region->name() == "LITEUART";
               }),
               "LiteX flash mode includes the LiteUART MMIO region");
    const auto flash_ram = std::find_if(regions.begin(), regions.end(), [](const auto& region) {
        return region->name() == "RAM";
    });
    CHECK_TRUE(flash_ram != regions.end(),
               "LiteX flash mode installs a named RAM region");
    if (flash_ram != regions.end()) {
        CHECK_EQ((*flash_ram)->size(), kExpectedFlashRamSize,
                 "LiteX flash mode keeps the legacy 64 MiB RAM window");
    }
}

static void test_litesdcard_stage0_read_path_and_irq_enable_race() {
    constexpr uint32_t CMD_DONE_IRQ = 1U << 3;
    std::vector<uint8_t> disk_bytes(static_cast<size_t>(DiskImage::kSectorSize * 4), 0);
    const char payload[] = "litesdcard-ok";
    std::memcpy(disk_bytes.data() + DiskImage::kSectorSize, payload, sizeof(payload) - 1);

    TempDiskImage disk = create_temp_disk_image(disk_bytes);
    CHECK_TRUE(!disk.path.empty(), "temp litesdcard image created");
    if (disk.path.empty()) {
        return;
    }

    MemoryBus bus;
    std::vector<Device*> devices;
    TestInterruptSink irq_sink;

    constexpr uint64_t ram_base = 0x1000;
    constexpr uint64_t sd_base = 0x5000;
    constexpr uint64_t buffer_addr = ram_base + 0x200;
    constexpr uint64_t reader_base = sd_base + LiteSdCardDevice::kReaderBase;
    constexpr uint64_t core_base = sd_base + LiteSdCardDevice::kCoreBase;
    constexpr uint64_t irq_base = sd_base + LiteSdCardDevice::kIrqBase;

    MachineConfig cfg;
    cfg.addRam(ram_base, 0x2000, "RAM")
       .addLiteSdCard(sd_base, disk.path, false, "LITESDCARD");
    cfg.applyTo(bus, devices, &irq_sink);

    CHECK_EQ(devices.size(), 1ULL, "MachineConfig collects LiteSDCard device");

    bus.write32(reader_base + 0x00, 0x00000000U);
    bus.write32(reader_base + 0x04, static_cast<uint32_t>(buffer_addr));
    bus.write32(reader_base + 0x08, 512U);
    bus.write8(reader_base + 0x0C, 1U);

    bus.write16(core_base + 0x24, 512U);
    bus.write32(core_base + 0x28, 1U);
    bus.write32(core_base + 0x00, 1U);
    bus.write32(core_base + 0x04, (17U << 8) | (1U << 5) | 1U);
    bus.write8(core_base + 0x08, 1U);

    CHECK_FALSE(irq_sink.asserted,
                "LiteSDCard defers IRQ assertion until the guest enables pending sources");
    CHECK_EQ(bus.read32(core_base + 0x1C) & 0x1U, 0x1U,
             "LiteSDCard reports command completion through CMD_EVENT");
    CHECK_EQ(bus.read32(core_base + 0x20) & 0x1U, 0x1U,
             "LiteSDCard reports data completion through DATA_EVENT");
    CHECK_EQ(bus.read8(reader_base + 0x10) & 0x1U, 0x1U,
             "LiteSDCard marks reader DMA completion once data reaches guest RAM");
    CHECK_EQ(bus.read8(buffer_addr + 0), static_cast<uint8_t>('l'),
             "LiteSDCard transfers disk sectors into guest RAM");
    CHECK_EQ(bus.read8(buffer_addr + 12), static_cast<uint8_t>('k'),
             "LiteSDCard preserves the copied DMA payload");

    bus.write32(irq_base + 0x08, CMD_DONE_IRQ);
    CHECK_TRUE(irq_sink.asserted,
               "Enabling CMD_DONE after a completed transfer replays the pending interrupt");
    CHECK_EQ(irq_sink.last_asserted, Little64Vectors::kPvBlockIrqVector,
             "LiteSDCard uses the shared high-bank IRQ vector used by the LiteX MMC DT");

    bus.write32(irq_base + 0x04, CMD_DONE_IRQ);
    CHECK_FALSE(irq_sink.asserted,
                "Acknowledging LiteSDCard IRQ_PENDING clears the interrupt line");
}

static void test_litex_flash_loader_uses_sd_layout_when_disk_is_attached() {
    Little64CPU cpu;
    const std::vector<uint8_t> flash_bytes = {0x00, 0xDF, 0x34, 0x12};
    const std::vector<uint8_t> disk_bytes(static_cast<size_t>(DiskImage::kSectorSize * 4), 0);

    TempDiskImage disk = create_temp_disk_image(disk_bytes);
    CHECK_TRUE(!disk.path.empty(), "temp LiteX SD image created");
    if (disk.path.empty()) {
        return;
    }

    cpu.setDiskImage(DiskImage::open(disk.path, true));
    CHECK_TRUE(cpu.loadProgramLiteXFlashImage(flash_bytes),
               "LiteX flash loader accepts an attached SD image");

    const auto& regions = cpu.getMemoryBus().regions();
    CHECK_EQ(regions.size(), 6ULL,
             "LiteX flash mode adds the LiteSDCard MMIO block alongside RAM, SRAM, flash, LiteUART, and timer");
    CHECK_TRUE(std::any_of(regions.begin(), regions.end(), [](const auto& region) {
                   return region->name() == "LITESDCARD";
               }),
               "LiteX flash mode includes the LiteSDCard MMIO region when a disk image is attached");
    CHECK_EQ(cpu.getMemoryBus().read8(0xF0001000ULL), 0x00,
             "The SD-capable LiteX layout does not leave a LiteUART block at the flash-only base");
    CHECK_EQ(cpu.getMemoryBus().read8(0xF0003804ULL), 0x00,
             "The SD-capable LiteX layout exposes LiteUART at the shifted CSR base");
}

static void test_litex_bootrom_loader_exposes_litedram_dfii_stub() {
    Little64CPU cpu;
    const std::vector<uint8_t> bootrom_bytes = {0x00, 0xDF, 0x34, 0x12};
    constexpr uint64_t kExpectedBootRomRamBase = 0x40000000ULL;
    constexpr uint64_t kExpectedBootRomRamSize = 256ULL * 1024ULL * 1024ULL;

    CHECK_TRUE(cpu.loadProgramLiteXBootRomImage(bootrom_bytes),
               "LiteX bootrom loader accepts a raw bootrom image");
    CHECK_EQ(cpu.registers.regs[15], 0x00000000ULL,
             "LiteX bootrom loader enters execution at the mapped bootrom base");
    CHECK_EQ(cpu.getMemoryBus().read16(0x00000000ULL), 0xDF00,
             "LiteX bootrom loader exposes the raw image through the bootrom window");
    CHECK_EQ(cpu.getMemoryBus().read32(0xF0003000ULL),
             LiteDramDfiiStubDevice::kControlHardwareMode,
             "LiteX bootrom mode exposes the LiteDRAM DFII stub in hardware-control mode");

    cpu.getMemoryBus().write32(0xF0003000ULL, 0x0E);
    cpu.getMemoryBus().write32(0xF000300CULL, 0x920);
    CHECK_EQ(cpu.getMemoryBus().read32(0xF0003000ULL), 0x0E,
             "LiteX bootrom mode keeps the LiteDRAM DFII control register writable");
    CHECK_EQ(cpu.getMemoryBus().read32(0xF000300CULL), 0x920,
             "LiteX bootrom mode keeps the LiteDRAM DFII address register writable");

    const auto& regions = cpu.getMemoryBus().regions();
    CHECK_EQ(regions.size(), 7ULL,
             "LiteX bootrom mode installs bootrom, flash, SRAM, RAM, LiteUART, timer, and LiteDRAM regions");
    CHECK_TRUE(std::any_of(regions.begin(), regions.end(), [](const auto& region) {
                   return region->name() == "LITEDRAM";
               }),
               "LiteX bootrom mode includes the LiteDRAM DFII stub region");
    const auto bootrom_ram = std::find_if(regions.begin(), regions.end(), [](const auto& region) {
        return region->name() == "RAM";
    });
    CHECK_TRUE(bootrom_ram != regions.end(),
               "LiteX bootrom mode installs a named RAM region");
    if (bootrom_ram != regions.end()) {
        CHECK_EQ((*bootrom_ram)->base(), kExpectedBootRomRamBase,
                 "LiteX bootrom mode maps RAM at the SDRAM base");
        CHECK_EQ((*bootrom_ram)->size(), kExpectedBootRomRamSize,
                 "LiteX bootrom mode exposes the Arty-sized SDRAM window");
    }
}

static void test_litex_bootrom_loader_uses_sd_layout_when_disk_is_attached() {
    Little64CPU cpu;
    const std::vector<uint8_t> bootrom_bytes = {0x00, 0xDF, 0x34, 0x12};
    const std::vector<uint8_t> disk_bytes(static_cast<size_t>(DiskImage::kSectorSize * 4), 0);

    TempDiskImage disk = create_temp_disk_image(disk_bytes);
    CHECK_TRUE(!disk.path.empty(), "temp LiteX bootrom SD image created");
    if (disk.path.empty()) {
        return;
    }

    cpu.setDiskImage(DiskImage::open(disk.path, true));
    CHECK_TRUE(cpu.loadProgramLiteXBootRomImage(bootrom_bytes),
               "LiteX bootrom loader accepts an attached SD image");

    const auto& regions = cpu.getMemoryBus().regions();
    CHECK_EQ(regions.size(), 8ULL,
             "LiteX bootrom mode adds LiteSDCard alongside bootrom, flash, SRAM, RAM, LiteDRAM, LiteUART, and timer");
    CHECK_TRUE(std::any_of(regions.begin(), regions.end(), [](const auto& region) {
                   return region->name() == "LITESDCARD";
               }),
               "LiteX bootrom mode includes the LiteSDCard MMIO region when a disk image is attached");
    CHECK_EQ(cpu.getMemoryBus().read8(0xF0004004ULL), 0x00,
             "The SDRAM-enabled LiteX bootrom layout exposes LiteUART at the shifted CSR base");
}

static void test_disk_image_open_uses_file_backed_io_for_sparse_images() {
    constexpr uint64_t sparse_size = 512ULL * 1024ULL * 1024ULL;
    constexpr uint64_t sparse_threshold = 64ULL * 1024ULL * 1024ULL;

    TempDiskImage disk = create_temp_sparse_disk_image(sparse_size);
    CHECK_TRUE(!disk.path.empty(), "temp sparse disk image created");
    if (disk.path.empty()) {
        return;
    }

    const uint64_t rss_before = current_rss_bytes();
    auto image = DiskImage::open(disk.path, false);
    const uint64_t rss_after = current_rss_bytes();

    CHECK_TRUE(image != nullptr, "DiskImage::open returns an object for sparse images");
    CHECK_TRUE(image && image->isValid(), "DiskImage::open keeps sparse images valid");
    CHECK_TRUE(image && image->lastError().empty(), "DiskImage::open does not report sparse-image errors");
    if (!image || !image->isValid() || !image->lastError().empty()) {
        return;
    }

    CHECK_EQ(image->sizeBytes(), sparse_size,
             "DiskImage reports the sparse file size without materializing the whole image");
    CHECK_EQ(image->sectorCount(), sparse_size / DiskImage::kSectorSize,
             "DiskImage exposes sector count for sparse images");
    if (rss_before != 0 && rss_after != 0) {
        CHECK_TRUE(rss_after >= rss_before && (rss_after - rss_before) < sparse_threshold,
                   "Opening a sparse disk image does not consume RAM proportional to the file size");
    }

    std::array<uint8_t, DiskImage::kSectorSize> readback{};
    CHECK_TRUE(image->read(sparse_size - readback.size(), readback.data(), readback.size()),
               "DiskImage can read the tail sector of a sparse image");
    CHECK_TRUE(std::all_of(readback.begin(), readback.end(), [](uint8_t byte) { return byte == 0; }),
               "Unwritten sparse sectors read back as zeros");

    constexpr std::array<uint8_t, 9> payload = {'s', 'p', 'a', 'r', 's', 'e', '-', 'o', 'k'};
    const uint64_t payload_offset = sparse_size - DiskImage::kSectorSize + 32;
    CHECK_TRUE(image->write(payload_offset, payload.data(), payload.size()),
               "DiskImage can write into a sparse image without buffering the whole file");
    CHECK_TRUE(image->flush(), "DiskImage flush persists sparse-image writes");

    auto reopened = DiskImage::open(disk.path, true);
    CHECK_TRUE(reopened != nullptr && reopened->isValid() && reopened->lastError().empty(),
               "DiskImage can reopen the sparse image after a write");
    if (!reopened || !reopened->isValid() || !reopened->lastError().empty()) {
        return;
    }

    std::array<uint8_t, payload.size()> persisted{};
    CHECK_TRUE(reopened->read(payload_offset, persisted.data(), persisted.size()),
               "DiskImage can read back sparse-image writes after reopen");
    CHECK_TRUE(std::equal(payload.begin(), payload.end(), persisted.begin()),
               "Sparse-image writes persist at the expected offset");
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

static void test_pending_irq_logs_once_while_delivery_is_deferred() {
    Little64CPU cpu;
    constexpr uint16_t MOVE_R0_TO_R0 = 0x1000;
    cpu.loadProgram(std::vector<uint16_t>{MOVE_R0_TO_R0, MOVE_R0_TO_R0, MOVE_R0_TO_R0, MOVE_R0_TO_R0});

    constexpr uint64_t IRQ_LINE = Little64Vectors::kSerialIrqVector;
    constexpr uint64_t IRQ_BIT = Little64Vectors::interruptBitForVector(IRQ_LINE);

    cpu.registers.interrupt_mask_high = IRQ_BIT;
    cpu.registers.setInterruptEnabled(true);
    cpu.registers.setInInterrupt(true);
    cpu.registers.setCurrentInterruptNumber(static_cast<uint8_t>(IRQ_LINE));

    cpu.assertInterrupt(IRQ_LINE);
    cpu.cycle();
    cpu.cycle();
    cpu.cycle();

    const std::string trace = capture_stderr([&]() {
        cpu.dumpBootLog("deferred irq trace test");
    });

    CHECK_EQ(count_occurrences(trace, "irq-raise"), 1ULL,
             "A latched IRQ is recorded once even if delivery is retried across multiple cycles");
    CHECK_EQ(count_occurrences(trace, "interrupt-enter"), 0ULL,
             "Deferred IRQ retries do not spuriously enter a handler while the same vector is active");
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
    test_liteuart_register_behavior_and_irq();
    test_litedram_dfii_stub_register_behavior();
    test_cpu_reset_resets_devices();
    test_litex_flash_loader_configures_litex_machine();
    test_litesdcard_stage0_read_path_and_irq_enable_race();
    test_litex_flash_loader_uses_sd_layout_when_disk_is_attached();
    test_litex_bootrom_loader_exposes_litedram_dfii_stub();
    test_litex_bootrom_loader_uses_sd_layout_when_disk_is_attached();
    test_disk_image_open_uses_file_backed_io_for_sparse_images();
    test_serial_rx_interrupt_line();
    test_serial_tx_interrupt_line();
    test_masked_irq_waits_until_reenabled();
    test_pending_irq_logs_once_while_delivery_is_deferred();
    test_mmio_trace_reaches_timer_device();
    test_mmio_trace_preserves_serial_printable_format();
    return print_summary();
}
