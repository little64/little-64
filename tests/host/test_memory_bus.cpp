#include "memory_bus.hpp"
#include "ram_region.hpp"
#include "rom_region.hpp"
#include "support/test_harness.hpp"

#include <cstdio>
#include <memory>
#include <vector>

class NoExecRamRegion : public RamRegion {
public:
    NoExecRamRegion(uint64_t base, uint64_t size, std::string_view name)
        : RamRegion(base, size, name) {}

    bool allows(uint64_t addr, size_t width, MemoryAccessType access) const override {
        if (!RamRegion::allows(addr, width, access)) {
            return false;
        }
        return access != MemoryAccessType::Execute;
    }
};

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

static void test_execute_access_intent() {
    MemoryBus bus;
    bus.addRegion(std::make_unique<RamRegion>(0x3000, 0x10, "RAMX"));
    bus.write16(0x3000, 0xBEEF);

    CHECK_EQ(bus.read16(0x3000, MemoryAccessType::Execute), 0xBEEF,
             "Execute access can fetch from executable region");
}

static void test_execute_permission_denied() {
    MemoryBus bus;
    bus.addRegion(std::make_unique<NoExecRamRegion>(0x4000, 0x10, "NOEXEC"));
    bus.write16(0x4000, 0x1234);

    CHECK_EQ(bus.read16(0x4000), 0x1234, "Normal read still works on no-exec region");
    CHECK_EQ(bus.read16(0x4000, MemoryAccessType::Execute), 0xFFFF,
             "Execute access denied falls back to unmapped-read value");
}

int main() {
    std::printf("=== Little-64 memory bus tests ===\n");
    test_unmapped_and_mapping_basics();
    test_overlap_rejected();
    test_cross_region_fallback();
    test_rom_is_read_only();
    test_execute_access_intent();
    test_execute_permission_denied();
    return print_summary();
}
