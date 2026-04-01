#include "memory_bus.hpp"
#include "ram_region.hpp"
#include "rom_region.hpp"
#include "support/test_harness.hpp"

#include <cstdio>
#include <memory>
#include <vector>

static void test_unmapped_and_mapping_basics() {
    MemoryBus bus;
    CHECK_EQ(bus.read8(0x1234), 0xFF, "Unmapped reads return 0xFF");

    bus.addRegion(std::make_unique<RamRegion>(0x1000, 0x100, "RAM0"));
    bus.write8(0x1000, 0xAB);
    CHECK_EQ(bus.read8(0x1000), 0xAB, "Mapped RAM reads/writes work");
}

static void test_overlap_rejected() {
    MemoryBus bus;
    bus.addRegion(std::make_unique<RamRegion>(0x1000, 0x100, "RAM0"));
    CHECK_THROWS(
        bus.addRegion(std::make_unique<RamRegion>(0x1080, 0x80, "RAM1")),
        "Overlapping regions are rejected");
}

static void test_cross_region_fallback() {
    MemoryBus bus;
    bus.addRegion(std::make_unique<RamRegion>(0x1000, 1, "RAMA"));
    bus.addRegion(std::make_unique<RamRegion>(0x1001, 1, "RAMB"));

    bus.write16(0x1000, 0xBEEF);
    CHECK_EQ(bus.read8(0x1000), 0xEF, "write16 writes low byte to first region");
    CHECK_EQ(bus.read8(0x1001), 0xBE, "write16 writes high byte to second region");
    CHECK_EQ(bus.read16(0x1000), 0xBEEF, "read16 reconstructs value across regions");
}

static void test_rom_is_read_only() {
    MemoryBus bus;
    bus.addRegion(std::make_unique<RomRegion>(0x2000, std::vector<uint8_t>{0xAA, 0xBB}, "ROM"));

    CHECK_EQ(bus.read8(0x2000), 0xAA, "ROM initial data visible");
    bus.write8(0x2000, 0x11);
    CHECK_EQ(bus.read8(0x2000), 0xAA, "ROM writes are ignored");
}

int main() {
    std::printf("=== Little-64 memory bus tests ===\n");
    test_unmapped_and_mapping_basics();
    test_overlap_rejected();
    test_cross_region_fallback();
    test_rom_is_read_only();
    return print_summary();
}
